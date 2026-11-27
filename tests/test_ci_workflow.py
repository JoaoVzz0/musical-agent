from __future__ import annotations

from pathlib import Path

import pytest
import yaml

WORKFLOW_FILE = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml"
YAML_ON_AS_BOOLEAN = True
DISPATCH_EVENT = "workflow_dispatch"
EVALS_JOB = "evals"
GITLEAKS_ACTION = "gitleaks/gitleaks-action@v2"
SKIP_NOTICE = "GOOGLE_API_KEY secret not set, evals skipped"
REQUIRED_COMMANDS = [
    "uv sync --locked",
    "uv run ruff check .",
    "uv run ruff format --check .",
    "uv run pytest",
    "uv run python scripts/dod_check.py --done",
    "uv run python scripts/check_comments.py",
]
EVAL_COMMANDS = ["uv run pytest -m evals", "uv run python evals/retrieval_eval.py"]


@pytest.fixture(scope="module")
def workflow() -> dict:
    return yaml.safe_load(WORKFLOW_FILE.read_text(encoding="utf-8"))


def triggers_of(workflow: dict) -> dict:
    return workflow.get("on", workflow.get(YAML_ON_AS_BOOLEAN))


def push_and_pr_jobs(workflow: dict) -> dict:
    return {name: job for name, job in workflow["jobs"].items() if name != EVALS_JOB}


def steps_of(jobs: dict) -> list[dict]:
    return [step for job in jobs.values() for step in job.get("steps", [])]


def commands_of(steps: list[dict]) -> str:
    return "\n".join(step.get("run", "") for step in steps)


def uses_of(steps: list[dict]) -> list[str]:
    return [step.get("uses", "") for step in steps]


@pytest.mark.dod("05.C1")
def test_workflow_triggers_on_push_pull_request_and_dispatch(workflow):
    triggers = triggers_of(workflow)

    assert {"push", "pull_request", DISPATCH_EVENT} <= set(triggers)


@pytest.mark.dod("05.C1")
@pytest.mark.parametrize("command", REQUIRED_COMMANDS)
def test_push_and_pr_jobs_run_required_command(workflow, command):
    commands = commands_of(steps_of(push_and_pr_jobs(workflow)))

    assert command in commands


@pytest.mark.dod("05.C1")
def test_deterministic_pytest_does_not_select_evals(workflow):
    lines = commands_of(steps_of(push_and_pr_jobs(workflow))).splitlines()

    pytest_lines = [line.strip() for line in lines if "uv run pytest" in line]
    assert pytest_lines
    assert all("evals" not in line for line in pytest_lines)


@pytest.mark.dod("05.C1")
def test_push_and_pr_jobs_set_up_uv(workflow):
    uses = uses_of(steps_of(push_and_pr_jobs(workflow)))

    assert any(action.startswith("astral-sh/setup-uv") for action in uses)


@pytest.mark.dod("05.C1")
def test_secret_scan_job_uses_gitleaks_with_full_history(workflow):
    jobs = push_and_pr_jobs(workflow)
    scan_job = next(job for job in jobs.values() if GITLEAKS_ACTION in uses_of(job["steps"]))

    checkout = next(
        s for s in scan_job["steps"] if s.get("uses", "").startswith("actions/checkout")
    )
    gitleaks = next(s for s in scan_job["steps"] if s.get("uses") == GITLEAKS_ACTION)
    assert checkout["with"]["fetch-depth"] == 0
    assert "GITHUB_TOKEN" in gitleaks["env"]


@pytest.mark.dod("05.C1")
def test_push_and_pr_jobs_are_not_conditional(workflow):
    jobs = push_and_pr_jobs(workflow)

    assert all("if" not in job for job in jobs.values())


@pytest.mark.dod("05.C1")
def test_evals_job_runs_only_on_workflow_dispatch(workflow):
    evals_job = workflow["jobs"][EVALS_JOB]

    assert evals_job["if"].replace(" ", "") == f"github.event_name=='{DISPATCH_EVENT}'"


@pytest.mark.dod("05.C1")
def test_evals_job_exposes_google_api_key_secret(workflow):
    evals_job = workflow["jobs"][EVALS_JOB]

    assert "secrets.GOOGLE_API_KEY" in evals_job["env"]["GOOGLE_API_KEY"]


@pytest.mark.dod("05.C1")
def test_evals_job_first_step_emits_notice_when_secret_missing(workflow):
    first_step = workflow["jobs"][EVALS_JOB]["steps"][0]

    assert "id" in first_step
    assert f"::notice::{SKIP_NOTICE}" in first_step["run"]
    assert "GITHUB_OUTPUT" in first_step["run"]


@pytest.mark.dod("05.C1")
def test_evals_job_later_steps_are_skipped_without_secret(workflow):
    steps = workflow["jobs"][EVALS_JOB]["steps"]
    check_id = steps[0]["id"]

    later_conditions = [step.get("if", "") for step in steps[1:]]
    assert later_conditions
    assert all(f"steps.{check_id}.outputs." in condition for condition in later_conditions)


@pytest.mark.dod("05.C1")
def test_evals_job_runs_eval_commands(workflow):
    commands = commands_of(workflow["jobs"][EVALS_JOB]["steps"])

    assert all(command in commands for command in EVAL_COMMANDS)


@pytest.mark.dod("05.C1")
def test_evals_job_uploads_reports_with_warning_when_missing(workflow):
    steps = workflow["jobs"][EVALS_JOB]["steps"]
    upload = next(s for s in steps if s.get("uses", "").startswith("actions/upload-artifact"))

    assert "evals/report.md" in upload["with"]["path"]
    assert "evals/retrieval_report.md" in upload["with"]["path"]
    assert upload["with"]["if-no-files-found"] == "warn"


def test_workflow_uses_least_privilege_permissions(workflow):
    assert workflow["permissions"] == {"contents": "read"}


def test_workflow_cancels_superseded_runs_on_same_ref(workflow):
    concurrency = workflow["concurrency"]

    assert "github.ref" in concurrency["group"]
    assert concurrency["cancel-in-progress"] is True
