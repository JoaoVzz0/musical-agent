from __future__ import annotations

import asyncio
import logging
import os
import re
import subprocess
import time
import unicodedata
from collections.abc import Awaitable, Callable, Iterable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field, fields
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

import yaml
from google.genai.errors import APIError

from evals.judge import Verdict
from musical_agent.config import PROJECT_ROOT, get_settings
from musical_agent.types import AgentReply

logger = logging.getLogger(__name__)

CASES_PATH = Path(__file__).with_name("cases.yaml")
REPORT_PATH = Path(__file__).with_name("report.md")

KNOWN_TOOLS = frozenset(
    {
        "search_products",
        "get_product_details",
        "get_order_status",
        "search_policies",
        "register_complaint",
    }
)
CATEGORY_MINIMUMS = {
    "catalog": 4,
    "availability": 2,
    "orders": 3,
    "policies": 5,
    "complaint": 1,
    "out_of_scope": 2,
    "red_team": 4,
}
CRITICAL = "critical"
SEVERITIES = frozenset({CRITICAL, "normal"})
ALWAYS_CRITICAL_CATEGORIES = frozenset({"red_team"})
MIN_TOTAL_CASES = 20
DOD_ID = re.compile(r"^\d{2}\.[A-Z]+\d+$")

PASSED, FAILED, RATE_LIMITED = "passed", "failed", "rate_limited"
HTTP_TOO_MANY_REQUESTS = 429
HTTP_SERVICE_UNAVAILABLE = 503
TRANSIENT_STATUS_CODES = frozenset({HTTP_TOO_MANY_REQUESTS, HTTP_SERVICE_UNAVAILABLE})
CRITICAL_ATTEMPTS = 3
NORMAL_ATTEMPTS = 1
DEFAULT_RETRY_DELAYS = (30.0, 60.0, 90.0)
DEFAULT_TURN_INTERVAL_S = 15.0
DEFAULT_CASE_DELAY_S = 4.0
CENTS_DIGITS = 2
GATE_OVERALL_MIN = 0.9
GATE_REQUIRED_CATEGORIES = frozenset({"red_team"})
GIT_TIMEOUT_S = 5
UNKNOWN_VERSION = "unknown"
AGENT_NOW_ENV = "AGENT_NOW"

BRL_VALUE = re.compile(r"R\$\s*(\d{1,3}(?:\.\d{3})+|\d+)(?:,(\d{1,2}))?(?!\d)")
PT_BR_NUMBER = re.compile(r"(\d{1,3}(?:\.\d{3})+|\d+)(?:,(\d+))?")
DOT_DECIMAL = re.compile(r"\d+\.\d+")
WHITESPACE = re.compile(r"\s+")

Responder = Callable[[str, str], Awaitable[AgentReply]]
Sleep = Callable[[float], Awaitable[None]]


class CaseSchemaError(ValueError):
    pass


class RubricJudge(Protocol):
    def evaluate(
        self,
        conversation: Sequence[tuple[str, str]],
        tool_outputs: Sequence[dict[str, Any]],
        criteria: str,
    ) -> Verdict: ...


@dataclass(frozen=True)
class EvalCase:
    id: str
    category: str
    agent_now: str
    turns: tuple[str, ...]
    expected_tools: tuple[str, ...]
    must_contain: tuple[str, ...]
    must_not_contain: tuple[str, ...]
    criteria: str
    severity: str
    ordered: bool = False
    dod: tuple[str, ...] = ()


@dataclass
class CaseResult:
    case_id: str
    category: str
    severity: str
    status: str
    attempts_run: int
    failures: list[str] = field(default_factory=list)
    tokens: int = 0
    latency_ms: int = 0


@dataclass(frozen=True)
class _AttemptOutcome:
    failures: list[str]
    tokens: int
    latency_ms: int


OPTIONAL_FIELDS = frozenset({"ordered", "dod"})
ALL_FIELDS = frozenset(f.name for f in fields(EvalCase))
REQUIRED_FIELDS = ALL_FIELDS - OPTIONAL_FIELDS
TUPLE_FIELDS = frozenset({"turns", "expected_tools", "must_contain", "must_not_contain", "dod"})


def _as_tuple(value: Any, name: str, case_id: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise CaseSchemaError(f"case {case_id}: '{name}' must be a list of strings")
    return tuple(value)


def _build_case(raw: Any) -> EvalCase:
    if not isinstance(raw, dict):
        raise CaseSchemaError(f"case must be a mapping, got {type(raw).__name__}")
    case_id = raw.get("id", "<no id>")
    missing = sorted(REQUIRED_FIELDS - raw.keys())
    unknown = sorted(raw.keys() - ALL_FIELDS)
    if missing or unknown:
        raise CaseSchemaError(f"case {case_id}: missing {missing}, unknown {unknown}")
    values = {
        key: _as_tuple(value, key, case_id) if key in TUPLE_FIELDS else value
        for key, value in raw.items()
    }
    return EvalCase(**values)


def load_cases(path: Path = CASES_PATH) -> list[EvalCase]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("cases"), list):
        raise CaseSchemaError(f"{path}: expected a top-level 'cases' list")
    return [_build_case(raw) for raw in data["cases"]]


def _is_iso_datetime(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        datetime.fromisoformat(value)
    except ValueError:
        return False
    return True


def _non_empty_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _case_problems(case: EvalCase) -> list[str]:
    prefix = f"case {case.id}"
    checks = [
        (case.category in CATEGORY_MINIMUMS, f"unknown category '{case.category}'"),
        (case.severity in SEVERITIES, f"invalid severity '{case.severity}'"),
        (_is_iso_datetime(case.agent_now), f"invalid agent_now '{case.agent_now}'"),
        (bool(case.turns) and all(map(_non_empty_text, case.turns)), "turns must be non-empty"),
        (_non_empty_text(case.criteria), "criteria must be non-empty"),
        (isinstance(case.ordered, bool), "ordered must be a boolean"),
        (
            case.category not in ALWAYS_CRITICAL_CATEGORIES or case.severity == CRITICAL,
            f"category '{case.category}' must be critical",
        ),
    ]
    problems = [f"{prefix}: {message}" for ok, message in checks if not ok]
    problems += [
        f"{prefix}: unknown tool '{tool}'"
        for tool in case.expected_tools
        if tool not in KNOWN_TOOLS
    ]
    problems += [f"{prefix}: invalid dod id '{dod}'" for dod in case.dod if not DOD_ID.match(dod)]
    return problems


def _coverage_problems(cases: Sequence[EvalCase]) -> list[str]:
    problems = []
    for category, minimum in CATEGORY_MINIMUMS.items():
        count = sum(1 for case in cases if case.category == category)
        if count < minimum:
            problems.append(f"coverage: category '{category}' has {count} cases, needs {minimum}")
    if len(cases) < MIN_TOTAL_CASES:
        problems.append(f"coverage: {len(cases)} cases, needs at least {MIN_TOTAL_CASES}")
    return problems


def _duplicate_id_problems(cases: Sequence[EvalCase]) -> list[str]:
    seen: set[str] = set()
    duplicates = {case.id for case in cases if case.id in seen or seen.add(case.id)}
    return [f"case {case_id}: duplicate id" for case_id in sorted(duplicates)]


def validate_cases(cases: Sequence[EvalCase]) -> list[str]:
    """Return schema and coverage problems; an empty list means the suite is valid."""
    problems = [problem for case in cases for problem in _case_problems(case)]
    return problems + _duplicate_id_problems(cases) + _coverage_problems(cases)


def normalize_text(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(char for char in decomposed if not unicodedata.combining(char))
    return WHITESPACE.sub(" ", stripped.casefold()).strip()


def _is_subsequence(expected: Sequence[str], called: Sequence[str]) -> bool:
    remaining = iter(called)
    return all(tool in remaining for tool in expected)


def _tool_problems(case: EvalCase, called: list[str]) -> list[str]:
    missing = [tool for tool in case.expected_tools if tool not in called]
    problems = [f"expected tool not called: {tool}" for tool in missing]
    if case.ordered and not missing and not _is_subsequence(case.expected_tools, called):
        problems.append(f"expected tools not called in order: {list(case.expected_tools)}")
    return problems


def check_deterministic(case: EvalCase, replies: Sequence[AgentReply]) -> list[str]:
    called = [name for reply in replies for name in reply.tools_called]
    text = normalize_text(" ".join(reply.text for reply in replies))
    problems = _tool_problems(case, called)
    problems += [
        f"missing required text: {needle!r}"
        for needle in case.must_contain
        if normalize_text(needle) not in text
    ]
    problems += [
        f"forbidden text present: {needle!r}"
        for needle in case.must_not_contain
        if normalize_text(needle) in text
    ]
    return problems


def _parse_pt_br(integer_part: str, decimal_part: str | None) -> float:
    return float(f"{integer_part.replace('.', '')}.{decimal_part or '0'}")


def extract_brl_values(text: str) -> list[float]:
    return [_parse_pt_br(whole, cents) for whole, cents in BRL_VALUE.findall(text)]


def _numbers_in_text(text: str) -> set[float]:
    pt_br = {_parse_pt_br(whole, decimal) for whole, decimal in PT_BR_NUMBER.findall(text)}
    dotted = {float(token) for token in DOT_DECIMAL.findall(text)}
    return {round(value, CENTS_DIGITS) for value in pt_br | dotted}


def _walk_numbers(value: Any) -> Iterator[float]:
    if isinstance(value, bool):
        return
    if isinstance(value, int | float):
        yield round(float(value), CENTS_DIGITS)
    elif isinstance(value, str):
        yield from _numbers_in_text(value)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _walk_numbers(item)
    elif isinstance(value, list | tuple):
        for item in value:
            yield from _walk_numbers(item)


def tool_numbers(reply: AgentReply) -> set[float]:
    return {number for call in reply.tool_calls for number in _walk_numbers(call.response)}


def check_grounding(reply: AgentReply, allowed_values: Iterable[float] = ()) -> list[str]:
    """Flag every `R$` value in the reply that no tool output of the turn contains.

    Args:
        reply: The agent reply for one turn, with its tool calls and responses.
        allowed_values: Extra legitimate values (numbers the customer typed, values from
            earlier turns of the same conversation).

    Returns:
        One problem per ungrounded value; empty when every value is grounded.
    """
    available = tool_numbers(reply) | {round(value, CENTS_DIGITS) for value in allowed_values}
    return [
        f"ungrounded R$ value {value} not found in tool outputs"
        for value in extract_brl_values(reply.text)
        if round(value, CENTS_DIGITS) not in available
    ]


def _grounding_failures(case: EvalCase, replies: Sequence[AgentReply]) -> list[str]:
    allowed = {number for turn in case.turns for number in _numbers_in_text(turn)}
    problems: list[str] = []
    for index, reply in enumerate(replies, start=1):
        problems += [f"turn {index}: {problem}" for problem in check_grounding(reply, allowed)]
        allowed |= tool_numbers(reply)
    return problems


@contextmanager
def pinned_now(agent_now: str) -> Iterator[None]:
    previous = os.environ.get(AGENT_NOW_ENV)
    os.environ[AGENT_NOW_ENV] = agent_now
    get_settings.cache_clear()
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(AGENT_NOW_ENV, None)
        else:
            os.environ[AGENT_NOW_ENV] = previous
        get_settings.cache_clear()


def _conversation(case: EvalCase, replies: Sequence[AgentReply]) -> list[tuple[str, str]]:
    pairs = zip(case.turns, replies, strict=False)
    return [entry for turn, reply in pairs for entry in (("customer", turn), ("agent", reply.text))]


def _tool_outputs(replies: Sequence[AgentReply]) -> list[dict[str, Any]]:
    return [
        {"turn": index, "name": call.name, "args": call.args, "response": call.response}
        for index, reply in enumerate(replies, start=1)
        for call in reply.tool_calls
    ]


async def _run_attempt(case: EvalCase, responder: Responder, judge: RubricJudge) -> _AttemptOutcome:
    session_id = f"eval-{case.id}-{uuid4().hex}"
    with pinned_now(case.agent_now):
        replies = [await responder(session_id, turn) for turn in case.turns]
    failures = check_deterministic(case, replies) + _grounding_failures(case, replies)
    if not failures:
        verdict = await asyncio.to_thread(
            judge.evaluate, _conversation(case, replies), _tool_outputs(replies), case.criteria
        )
        failures = [] if verdict.passed else [f"judge: {verdict.reason}"]
    tokens = sum(reply.tokens for reply in replies)
    latency = sum(reply.latency_ms for reply in replies)
    return _AttemptOutcome(failures=failures, tokens=tokens, latency_ms=latency)


def is_rate_limit(error: APIError) -> bool:
    return error.code in TRANSIENT_STATUS_CODES


def paced(
    responder: Responder,
    min_interval_s: float = DEFAULT_TURN_INTERVAL_S,
    clock: Callable[[], float] = time.monotonic,
    sleep: Sleep = asyncio.sleep,
) -> Responder:
    """Space consecutive turns so a run stays inside the free tier's requests per minute."""
    last_start: list[float] = []

    async def paced_responder(session_id: str, message: str) -> AgentReply:
        if last_start:
            remaining = min_interval_s - (clock() - last_start[0])
            if remaining > 0:
                await sleep(remaining)
        last_start[:] = [clock()]
        return await responder(session_id, message)

    return paced_responder


async def _attempt_with_retry(
    case: EvalCase,
    responder: Responder,
    judge: RubricJudge,
    retry_delays: Sequence[float],
    sleep: Sleep,
) -> _AttemptOutcome | None:
    for delay in (*retry_delays, None):
        try:
            return await _run_attempt(case, responder, judge)
        except APIError as error:
            if not is_rate_limit(error):
                raise
            if delay is None:
                logger.warning("case %s still rate limited after retries", case.id)
                return None
            logger.info("case %s rate limited, retrying in %.1fs", case.id, delay)
            await sleep(delay)
    return None


async def run_case(
    case: EvalCase,
    responder: Responder,
    judge: RubricJudge,
    attempts: int,
    *,
    retry_delays: Sequence[float] = DEFAULT_RETRY_DELAYS,
    sleep: Sleep = asyncio.sleep,
) -> CaseResult:
    """Run a case `attempts` times (fresh session each); it passes only if every attempt passes.

    A 429 that survives every retry makes the result `rate_limited`, which is never a failure.
    """
    result = CaseResult(case.id, case.category, case.severity, PASSED, attempts_run=0)
    for attempt in range(1, attempts + 1):
        outcome = await _attempt_with_retry(case, responder, judge, retry_delays, sleep)
        if outcome is None:
            result.status = RATE_LIMITED
            return result
        result.attempts_run = attempt
        result.tokens += outcome.tokens
        result.latency_ms += outcome.latency_ms
        if outcome.failures:
            result.status = FAILED
            result.failures = [f"attempt {attempt}: {failure}" for failure in outcome.failures]
            return result
    return result


def attempts_for(case: EvalCase, critical_attempts: int = CRITICAL_ATTEMPTS) -> int:
    return critical_attempts if case.severity == CRITICAL else NORMAL_ATTEMPTS


async def run_suite(
    cases: Sequence[EvalCase],
    responder: Responder,
    judge: RubricJudge,
    *,
    critical_attempts: int = CRITICAL_ATTEMPTS,
    case_delay_s: float = DEFAULT_CASE_DELAY_S,
    retry_delays: Sequence[float] = DEFAULT_RETRY_DELAYS,
    sleep: Sleep = asyncio.sleep,
) -> list[CaseResult]:
    results = []
    for index, case in enumerate(cases):
        if index:
            await sleep(case_delay_s)
        attempts = attempts_for(case, critical_attempts)
        result = await run_case(
            case, responder, judge, attempts, retry_delays=retry_delays, sleep=sleep
        )
        logger.info("case %s: %s", case.id, result.status)
        results.append(result)
    return results


def _evaluated(results: Iterable[CaseResult]) -> list[CaseResult]:
    return [result for result in results if result.status != RATE_LIMITED]


def pass_rate(results: Iterable[CaseResult]) -> float:
    evaluated = _evaluated(results)
    if not evaluated:
        return 0.0
    return sum(result.status == PASSED for result in evaluated) / len(evaluated)


def gate_passed(results: Sequence[CaseResult]) -> bool:
    """Gate: >= 90% overall, every critical and red_team case passed (rate limited excluded)."""
    evaluated = _evaluated(results)
    if not evaluated:
        return False
    must_pass = [
        result
        for result in evaluated
        if result.severity == CRITICAL or result.category in GATE_REQUIRED_CATEGORIES
    ]
    all_required = all(result.status == PASSED for result in must_pass)
    return pass_rate(evaluated) >= GATE_OVERALL_MIN and all_required


def git_short_hash() -> str:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            cwd=PROJECT_ROOT,
            timeout=GIT_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError):
        return UNKNOWN_VERSION
    return completed.stdout.strip() or UNKNOWN_VERSION


def _rate_row(scope: str, results: Sequence[CaseResult]) -> str:
    evaluated = _evaluated(results)
    passed = sum(result.status == PASSED for result in evaluated)
    return f"| {scope} | {passed} | {len(evaluated)} | {pass_rate(results):.0%} |"


def _pass_rate_section(results: Sequence[CaseResult]) -> list[str]:
    categories = sorted({result.category for result in results})
    rows = [_rate_row("overall", results)]
    rows += [_rate_row(name, [r for r in results if r.category == name]) for name in categories]
    return ["## Pass rate", "", "| Scope | Passed | Evaluated | Rate |", "|---|---|---|---|", *rows]


def _case_list(results: Sequence[CaseResult], status: str, with_reasons: bool) -> list[str]:
    selected = [result for result in results if result.status == status]
    if not selected:
        return ["None."]
    return [
        f"- `{r.case_id}` ({r.category}, {r.severity})"
        + (f": {'; '.join(r.failures)}" if with_reasons else "")
        for r in selected
    ]


def _cases_table(results: Sequence[CaseResult]) -> list[str]:
    header = [
        "| Case | Category | Severity | Status | Attempts | Tokens | Latency (ms) |",
        "|---|---|---|---|---|---|---|",
    ]
    rows = [
        f"| `{r.case_id}` | {r.category} | {r.severity} | {r.status} | {r.attempts_run} "
        f"| {r.tokens} | {r.latency_ms} |"
        for r in results
    ]
    return header + rows


def write_report(
    results: Sequence[CaseResult], path: Path, model: str, prompt_version: str
) -> None:
    gate = "PASSED" if gate_passed(results) else "FAILED"
    lines = [
        "# Agent eval report",
        "",
        f"- Model: `{model}`",
        f"- Prompt version: `{prompt_version}`",
        f"- Generated: {datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"- Gate (>= 90% overall, 100% critical, 100% red_team): **{gate}**",
        "- Tokens and latency are totals over all attempts and turns of a case.",
        "",
        *_pass_rate_section(results),
        "",
        "## Failed cases",
        "",
        *_case_list(results, FAILED, with_reasons=True),
        "",
        "## Rate limited",
        "",
        *_case_list(results, RATE_LIMITED, with_reasons=False),
        "",
        "## Cases",
        "",
        *_cases_table(results),
        "",
        "## Judge spot-check",
        "",
        "_To fill by hand: re-read N judge verdicts, record agreement (k/N) and disagreements._",
        "",
    ]
    Path(path).write_text("\n".join(lines), encoding="utf-8")
