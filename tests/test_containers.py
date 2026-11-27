from __future__ import annotations

import pytest
import yaml

from musical_agent.config import PROJECT_ROOT

COMPOSE_PATH = PROJECT_ROOT / "compose.yaml"
DOCKERFILE_PATH = PROJECT_ROOT / "Dockerfile"
DOCKERIGNORE_PATH = PROJECT_ROOT / ".dockerignore"
WEB_PORT = "8000"


def services() -> dict:
    return yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))["services"]


def command_text(service: dict) -> str:
    command = service.get("command", "")
    return " ".join(command) if isinstance(command, list) else command


@pytest.mark.dod("05.E1")
def test_web_service_serves_adk_web_on_port_8000_by_default():
    web = services()["web"]

    assert "adk web" in command_text(web)
    assert "0.0.0.0" in command_text(web)
    assert any(str(port).endswith(f"{WEB_PORT}:{WEB_PORT}") for port in web["ports"])
    assert "profiles" not in web


@pytest.mark.dod("05.E1")
def test_chat_service_is_interactive_and_opt_in():
    chat = services()["chat"]

    assert chat["stdin_open"] is True
    assert chat["tty"] is True
    assert chat["profiles"] == ["cli"]
    assert "musical-agent" in command_text(chat)


@pytest.mark.dod("05.E1")
def test_tests_service_runs_pytest_without_a_key():
    tests = services()["tests"]

    assert tests["profiles"] == ["test"]
    assert "pytest" in command_text(tests)
    assert tests["build"]["target"] == "test"


@pytest.mark.dod("05.E1")
@pytest.mark.parametrize("name", ["web", "chat", "tests"])
def test_env_file_is_optional_and_var_is_mounted(name):
    service = services()[name]

    assert {"path": ".env", "required": False} in service["env_file"]
    assert any(str(volume).startswith("./var:") for volume in service.get("volumes", []))


@pytest.mark.dod("05.E2")
def test_dockerfile_installs_locked_dependencies_with_app_and_test_targets():
    dockerfile = DOCKERFILE_PATH.read_text(encoding="utf-8")

    assert "uv sync --locked" in dockerfile
    assert " AS app" in dockerfile
    assert " AS test" in dockerfile


@pytest.mark.dod("05.E2")
def test_dockerfile_runs_as_non_root_user():
    user_lines = [
        line
        for line in DOCKERFILE_PATH.read_text(encoding="utf-8").splitlines()
        if line.startswith("USER ")
    ]

    assert user_lines
    assert all(line.split()[1] not in {"root", "0"} for line in user_lines)


@pytest.mark.dod("05.E2")
@pytest.mark.parametrize("pattern", [".env", ".venv", "var", "challenge", ".git"])
def test_dockerignore_keeps_secrets_and_local_state_out_of_the_image(pattern):
    entries = {
        line.strip().rstrip("/")
        for line in DOCKERIGNORE_PATH.read_text(encoding="utf-8").splitlines()
    }

    assert pattern in entries
