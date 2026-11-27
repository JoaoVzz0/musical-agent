from __future__ import annotations

import asyncio
from collections.abc import Iterator

import pytest

from evals.judge import JUDGE_MODEL, Judge, default_generate
from evals.runner import (
    CASES_PATH,
    DEFAULT_CASE_DELAY_S,
    RATE_LIMITED,
    REPORT_PATH,
    CaseResult,
    EvalCase,
    Responder,
    attempts_for,
    gate_passed,
    git_short_hash,
    load_cases,
    run_case,
    write_report,
)
from musical_agent.config import get_settings

CASES = load_cases(CASES_PATH)
RESULTS: list[CaseResult] = []

pytestmark = pytest.mark.evals


@pytest.fixture(scope="module")
def responder() -> Responder:
    from musical_agent.agent.agent import respond

    return respond


@pytest.fixture(scope="module")
def judge() -> Judge:
    return Judge(default_generate(JUDGE_MODEL))


@pytest.fixture(scope="module", autouse=True)
def report() -> Iterator[None]:
    yield
    if RESULTS:
        write_report(RESULTS, REPORT_PATH, get_settings().model, git_short_hash())


@pytest.mark.parametrize("case", CASES, ids=[case.id for case in CASES])
async def test_case(case: EvalCase, responder: Responder, judge: Judge) -> None:
    if RESULTS:
        await asyncio.sleep(DEFAULT_CASE_DELAY_S)

    result = await run_case(case, responder, judge, attempts_for(case))
    RESULTS.append(result)

    if result.status == RATE_LIMITED:
        pytest.skip(f"{case.id} rate limited")
    assert result.failures == []


def test_gate() -> None:
    if not RESULTS:
        pytest.skip("no eval case ran")

    passed = gate_passed(RESULTS)

    assert passed, f"gate failed, see {REPORT_PATH}"
