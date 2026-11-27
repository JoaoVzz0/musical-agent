from __future__ import annotations

import asyncio
import json
import os
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from google.genai.errors import ClientError, ServerError

from evals.judge import Judge, Verdict
from evals.runner import (
    CASES_PATH,
    CaseResult,
    CaseSchemaError,
    EvalCase,
    check_deterministic,
    check_grounding,
    extract_brl_values,
    gate_passed,
    load_cases,
    paced,
    run_case,
    run_suite,
    validate_cases,
    write_report,
)
from musical_agent.types import AgentReply, ToolCallRecord

PINNED_NOW = "2026-02-20T10:00:00-04:00"
OVERLOADED_PAYLOAD = {"error": {"code": 503, "message": "high demand", "status": "UNAVAILABLE"}}
RATE_LIMIT_PAYLOAD = {"error": {"code": 429, "message": "quota", "status": "RESOURCE_EXHAUSTED"}}
PASSING_JUDGE_OUTPUT = '{"passed": true, "reason": "ok"}'
FAILING_JUDGE_OUTPUT = '{"passed": false, "reason": "tom ríspido"}'
NO_RETRY_DELAYS = (0.0, 0.0)


def make_case(**overrides: object) -> EvalCase:
    base = EvalCase(
        id="takamine_price",
        category="catalog",
        agent_now="2026-03-25T10:00:00-04:00",
        turns=("quanto ta o takamine gd20?",),
        expected_tools=("get_product_details",),
        must_contain=("R$ 2.199,00",),
        must_not_contain=("12%",),
        criteria="Informa o preço do Takamine GD20.",
        severity="normal",
    )
    return replace(base, **overrides)


def make_reply(
    text: str = "O Takamine GD20 sai por R$ 2.199,00.",
    tools: tuple[str, ...] = ("get_product_details",),
    response: dict | None = None,
) -> AgentReply:
    payload = response if response is not None else {"status": "ok", "final_price": 2199.0}
    calls = [ToolCallRecord(name=name, args={}, response=payload) for name in tools]
    return AgentReply(
        text=text,
        tools_called=list(tools),
        tool_calls=calls,
        tokens=100,
        latency_ms=50,
        blocked=False,
    )


class FakeResponder:
    def __init__(self, reply: AgentReply | None = None, rate_limited_calls: int = 0) -> None:
        self.reply = reply or make_reply()
        self.rate_limited_calls = rate_limited_calls
        self.sessions: list[str] = []
        self.seen_now: list[str | None] = []

    async def __call__(self, session_id: str, message: str) -> AgentReply:
        self.sessions.append(session_id)
        self.seen_now.append(os.environ.get("AGENT_NOW"))
        if self.rate_limited_calls > 0:
            self.rate_limited_calls -= 1
            raise ClientError(429, RATE_LIMIT_PAYLOAD)
        return self.reply


class SequenceJudge:
    def __init__(self, verdicts: list[bool]) -> None:
        self.verdicts = list(verdicts)

    def evaluate(self, conversation: list, tool_outputs: list, criteria: str) -> Verdict:
        return Verdict(passed=self.verdicts.pop(0), reason="fake")


async def no_sleep(_: float) -> None:
    return None


def passing_judge() -> Judge:
    return Judge(lambda _prompt: PASSING_JUDGE_OUTPUT)


def result(case_id: str, category: str, severity: str, status: str) -> CaseResult:
    return CaseResult(
        case_id=case_id,
        category=category,
        severity=severity,
        status=status,
        attempts_run=1,
        failures=[] if status != "failed" else ["boom"],
        tokens=10,
        latency_ms=5,
    )


@pytest.mark.dod("05.A1")
def test_cases_yaml_is_schema_valid_and_meets_coverage() -> None:
    cases = load_cases(CASES_PATH)

    problems = validate_cases(cases)

    assert problems == []


@pytest.mark.dod("05.A1")
def test_cases_yaml_automates_manual_dod_rows_of_phase_04() -> None:
    cases = load_cases(CASES_PATH)

    dod_ids = {dod_id for case in cases for dod_id in case.dod}

    assert {"04.M1", "04.M2"} <= dod_ids


@pytest.mark.dod("05.A1")
def test_load_cases_rejects_case_missing_required_field(tmp_path: Path) -> None:
    path = tmp_path / "cases.yaml"
    path.write_text("cases:\n  - id: only_id\n    category: catalog\n", encoding="utf-8")

    with pytest.raises(CaseSchemaError):
        load_cases(path)


@pytest.mark.dod("05.A1")
def test_validate_cases_reports_category_below_minimum() -> None:
    cases = [make_case()]

    problems = validate_cases(cases)

    assert any("red_team" in problem for problem in problems)


@pytest.mark.dod("05.A1")
def test_validate_cases_rejects_unknown_severity_and_tool() -> None:
    case = make_case(severity="urgent", expected_tools=("delete_database",))

    problems = validate_cases([case])

    assert any("severity" in problem for problem in problems)
    assert any("delete_database" in problem for problem in problems)


@pytest.mark.dod("05.A1")
def test_validate_cases_requires_red_team_to_be_critical() -> None:
    case = make_case(id="leak", category="red_team", severity="normal")

    problems = validate_cases([case])

    assert any("leak" in problem and "critical" in problem for problem in problems)


@pytest.mark.dod("05.A1")
def test_validate_cases_rejects_invalid_agent_now() -> None:
    case = make_case(agent_now="ontem de manhã")

    problems = validate_cases([case])

    assert any("agent_now" in problem for problem in problems)


@pytest.mark.dod("05.A2")
def test_extract_brl_values_parses_pt_br_format() -> None:
    text = "De R$ 2.199,00 por R$2.089,05 no PIX, ou 12x de R$ 183,25. Frete R$ 35."

    values = extract_brl_values(text)

    assert values == [2199.0, 2089.05, 183.25, 35.0]


@pytest.mark.dod("05.A2")
def test_extract_brl_values_handles_non_breaking_space_and_millions() -> None:
    text = "Total R$ 1.234.567,8"

    values = extract_brl_values(text)

    assert values == [1234567.8]


@pytest.mark.dod("05.A2")
def test_grounding_passes_when_values_appear_in_nested_tool_outputs() -> None:
    response = {"products": [{"final_price": 323.1, "original_price": 359}]}
    reply = make_reply(text="De R$ 359,00 por R$ 323,10.", response=response)

    problems = check_grounding(reply)

    assert problems == []


@pytest.mark.dod("05.A2")
def test_grounding_flags_value_absent_from_tool_outputs() -> None:
    reply = make_reply(text="Hoje sai por R$ 1.099,50 pra você.")

    problems = check_grounding(reply)

    assert any("1099.5" in problem for problem in problems)


@pytest.mark.dod("05.A2")
def test_grounding_passes_reply_without_prices() -> None:
    reply = make_reply(text="Oi! Como posso ajudar?", tools=())

    problems = check_grounding(reply)

    assert problems == []


@pytest.mark.dod("05.A2")
def test_grounding_accepts_values_quoted_in_tool_text() -> None:
    response = {"passages": [{"text": "Frete grátis para pedidos acima de R$ 500,00."}]}
    reply = make_reply(text="Acima de R$ 500,00 o frete é grátis.", response=response)

    problems = check_grounding(reply)

    assert problems == []


@pytest.mark.dod("05.A2")
def test_grounding_accepts_explicitly_allowed_values() -> None:
    reply = make_reply(text="Separei violões até R$ 1.000,00.", tools=())

    problems = check_grounding(reply, allowed_values=[1000.0])

    assert problems == []


@pytest.mark.dod("05.A3")
def test_judge_parses_passed_verdict() -> None:
    judge = passing_judge()

    verdict = judge.evaluate([("customer", "oi"), ("agent", "olá")], [], "Cumprimenta.")

    assert verdict == Verdict(passed=True, reason="ok")


@pytest.mark.dod("05.A3")
def test_judge_parses_failed_verdict() -> None:
    judge = Judge(lambda _prompt: FAILING_JUDGE_OUTPUT)

    verdict = judge.evaluate([("customer", "oi")], [], "Cumprimenta.")

    assert verdict == Verdict(passed=False, reason="tom ríspido")


@pytest.mark.dod("05.A3")
def test_judge_accepts_json_wrapped_in_code_fence() -> None:
    judge = Judge(lambda _prompt: f"```json\n{PASSING_JUDGE_OUTPUT}\n```")

    verdict = judge.evaluate([("customer", "oi")], [], "Cumprimenta.")

    assert verdict.passed is True


@pytest.mark.dod("05.A3")
@pytest.mark.parametrize(
    "raw",
    [
        "claro, passou!",
        '{"passed": true}',
        '{"reason": "faltou"}',
        '{"passed": "yes", "reason": "ok"}',
        '{"passed": true, "reason": 3}',
        '[true, "ok"]',
        "",
    ],
)
def test_judge_treats_malformed_output_as_failure(raw: str) -> None:
    judge = Judge(lambda _prompt: raw)

    verdict = judge.evaluate([("customer", "oi")], [], "Cumprimenta.")

    assert verdict.passed is False
    assert "malformed" in verdict.reason


@pytest.mark.dod("05.A3")
def test_judge_prompt_holds_conversation_tool_outputs_and_rubric() -> None:
    prompts: list[str] = []
    judge = Judge(lambda prompt: prompts.append(prompt) or PASSING_JUDGE_OUTPUT)
    tool_outputs = [{"name": "get_product_details", "response": {"final_price": 2199.0}}]

    judge.evaluate([("customer", "quanto ta?")], tool_outputs, "Cita o preço sem 12%.")

    assert "quanto ta?" in prompts[0]
    assert "2199.0" in prompts[0]
    assert "Cita o preço sem 12%." in prompts[0]


@pytest.mark.dod("05.A4")
async def test_critical_case_runs_three_times_in_suite() -> None:
    responder = FakeResponder()
    case = make_case(severity="critical")

    results = await run_suite([case], responder, passing_judge(), sleep=no_sleep)

    assert results[0].attempts_run == 3
    assert len(responder.sessions) == 3
    assert results[0].status == "passed"


@pytest.mark.dod("05.A4")
async def test_normal_case_runs_once_in_suite() -> None:
    responder = FakeResponder()

    results = await run_suite([make_case()], responder, passing_judge(), sleep=no_sleep)

    assert results[0].attempts_run == 1
    assert len(responder.sessions) == 1


@pytest.mark.dod("05.A4")
async def test_critical_case_fails_when_one_of_three_attempts_fails() -> None:
    case = make_case(severity="critical")
    judge = SequenceJudge([True, False, True])

    outcome = await run_case(case, FakeResponder(), judge, attempts=3, sleep=no_sleep)

    assert outcome.status == "failed"


@pytest.mark.dod("05.A4")
async def test_persistent_429_is_reported_as_rate_limited_not_failure() -> None:
    responder = FakeResponder(rate_limited_calls=99)

    outcome = await run_case(
        make_case(), responder, passing_judge(), attempts=1, retry_delays=NO_RETRY_DELAYS
    )

    assert outcome.status == "rate_limited"
    assert outcome.failures == []


@pytest.mark.dod("05.A4")
async def test_429_is_retried_with_backoff_then_passes() -> None:
    responder = FakeResponder(rate_limited_calls=1)
    delays: list[float] = []

    async def record_sleep(seconds: float) -> None:
        delays.append(seconds)

    outcome = await run_case(
        make_case(),
        responder,
        passing_judge(),
        attempts=1,
        retry_delays=(2.0, 4.0),
        sleep=record_sleep,
    )

    assert outcome.status == "passed"
    assert delays == [2.0]


@pytest.mark.dod("05.A4")
async def test_judge_429_is_reported_as_rate_limited() -> None:
    def rate_limited_generate(_prompt: str) -> str:
        raise ClientError(429, RATE_LIMIT_PAYLOAD)

    outcome = await run_case(
        make_case(),
        FakeResponder(),
        Judge(rate_limited_generate),
        attempts=1,
        retry_delays=NO_RETRY_DELAYS,
        sleep=no_sleep,
    )

    assert outcome.status == "rate_limited"


@pytest.mark.dod("05.A4")
def test_gate_ignores_rate_limited_cases() -> None:
    results = [
        result("a", "catalog", "normal", "passed"),
        result("b", "red_team", "critical", "rate_limited"),
    ]

    assert gate_passed(results) is True


@pytest.mark.dod("05.A4")
def test_gate_fails_on_any_failed_red_team_case() -> None:
    passed = [result(f"c{index}", "catalog", "normal", "passed") for index in range(20)]
    failed = [result("leak", "red_team", "critical", "failed")]

    assert gate_passed(passed + failed) is False


@pytest.mark.dod("05.A4")
def test_report_lists_rate_limited_separately_from_failures(tmp_path: Path) -> None:
    path = tmp_path / "report.md"
    results = [
        result("ok_case", "catalog", "normal", "passed"),
        result("bad_case", "orders", "critical", "failed"),
        result("slow_case", "policies", "normal", "rate_limited"),
    ]

    write_report(results, path, model="gemini-3.5-flash", prompt_version="abc1234")

    report = path.read_text(encoding="utf-8")
    failed_section = report.split("## Failed cases")[1].split("## Rate limited")[0]
    assert "bad_case" in failed_section
    assert "slow_case" not in failed_section
    assert "slow_case" in report.split("## Rate limited")[1]
    assert "gemini-3.5-flash" in report
    assert "abc1234" in report
    assert "Judge spot-check" in report


def test_each_attempt_uses_a_fresh_session() -> None:
    responder = FakeResponder()
    case = make_case(turns=("oi", "quanto ta o takamine?"))

    asyncio.run(run_case(case, responder, passing_judge(), attempts=2, sleep=no_sleep))

    first, second = responder.sessions[0:2], responder.sessions[2:4]
    assert first[0] == first[1]
    assert first[0] != second[0]


async def test_run_case_pins_agent_now_and_restores_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_NOW", "")
    responder = FakeResponder()

    await run_case(make_case(agent_now=PINNED_NOW), responder, passing_judge(), attempts=1)

    assert responder.seen_now == [PINNED_NOW]
    assert os.environ["AGENT_NOW"] == ""


async def test_judge_is_skipped_when_deterministic_check_fails() -> None:
    responder = FakeResponder(reply=make_reply(text="Sai por R$ 2.199,00 com 12% off."))
    judge = SequenceJudge([])

    outcome = await run_case(make_case(), responder, judge, attempts=1, sleep=no_sleep)

    assert outcome.status == "failed"
    assert any("12%" in failure for failure in outcome.failures)


def test_deterministic_flags_missing_expected_tool() -> None:
    reply = make_reply(tools=("search_products",), response={"final_price": 2199.0})

    problems = check_deterministic(make_case(), [reply])

    assert any("get_product_details" in problem for problem in problems)


def test_deterministic_matching_ignores_case_and_accents() -> None:
    case = make_case(must_contain=("violao", "r$ 2.199,00"), must_not_contain=())
    reply = make_reply(text="O VIOLÃO sai por R$ 2.199,00.")

    problems = check_deterministic(case, [reply])

    assert problems == []


def test_deterministic_ordered_tools_require_order() -> None:
    case = make_case(expected_tools=("search_products", "get_product_details"), ordered=True)
    reply = make_reply(tools=("get_product_details", "search_products"))

    problems = check_deterministic(case, [reply])

    assert any("order" in problem for problem in problems)


def test_judge_receives_tool_outputs_as_json_serializable() -> None:
    captured: list[str] = []
    judge = Judge(lambda prompt: captured.append(prompt) or PASSING_JUDGE_OUTPUT)

    judge.evaluate([("customer", "oi")], [{"name": "x", "response": {"a": [1, 2]}}], "r")

    assert json.dumps({"a": [1, 2]}) in captured[0]


@pytest.mark.dod("05.A4")
async def test_overloaded_model_503_is_retried_like_a_rate_limit() -> None:
    calls = 0

    async def overloaded_once(session_id: str, message: str) -> AgentReply:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ServerError(503, OVERLOADED_PAYLOAD)
        return AgentReply("ok", [], [], 10, 100, False)

    async def no_sleep(_seconds: float) -> None:
        return None

    case = replace(make_case(), expected_tools=(), must_contain=(), must_not_contain=())
    outcome = await run_case(
        case, overloaded_once, passing_judge(), attempts=1, retry_delays=(1.0,), sleep=no_sleep
    )

    assert outcome.status == "passed"
    assert calls == 2


@pytest.mark.dod("05.A4")
async def test_paced_responder_keeps_a_minimum_interval_between_turns() -> None:
    now = [100.0]
    waits: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        waits.append(seconds)
        now[0] += seconds

    async def instant(session_id: str, message: str) -> AgentReply:
        now[0] += 5.0
        return AgentReply(message, [], [], 0, 0, False)

    responder = paced(instant, min_interval_s=36.0, clock=lambda: now[0], sleep=fake_sleep)

    await responder("s", "first")
    await responder("s", "second")

    assert waits == [31.0]


@pytest.mark.dod("05.A4")
async def test_dropped_connection_is_retried_like_a_rate_limit() -> None:
    calls = 0

    async def disconnects_once(session_id: str, message: str) -> AgentReply:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.RemoteProtocolError("Server disconnected without sending a response.")
        return AgentReply("ok", [], [], 10, 100, False)

    async def no_sleep(_seconds: float) -> None:
        return None

    case = replace(make_case(), expected_tools=(), must_contain=(), must_not_contain=())
    outcome = await run_case(
        case, disconnects_once, passing_judge(), attempts=1, retry_delays=(1.0,), sleep=no_sleep
    )

    assert outcome.status == "passed"
    assert calls == 2
