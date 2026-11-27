from __future__ import annotations

import io
import logging
import stat
from collections.abc import Callable, Iterable
from pathlib import Path

import pytest
from google.genai.errors import APIError, ClientError, ServerError
from pydantic import SecretStr
from rich.console import Console

from musical_agent.config import Settings
from musical_agent.interfaces.cli import CliDeps, main, write_api_key
from musical_agent.types import AgentReply, ToolCallRecord

FAKE_KEY = "AIzaFAKE-secret-key-123"


class FakeResponder:
    def __init__(self, error: Exception | None = None) -> None:
        self.calls: list[tuple[str, str]] = []
        self.error = error

    async def __call__(
        self, session_id: str, message: str, user_id: str = "customer"
    ) -> AgentReply:
        self.calls.append((session_id, message))
        if self.error is not None:
            raise self.error
        return AgentReply(
            text=f"eco: {message}",
            tools_called=["search_products", "get_order"],
            tool_calls=[ToolCallRecord(name="search_products", args={}, response=None)],
            tokens=321,
            latency_ms=654,
            blocked=False,
        )


def line_reader(lines: Iterable[str]) -> Callable[[], str]:
    iterator = iter(lines)

    def read() -> str:
        try:
            return next(iterator)
        except StopIteration as exc:
            raise EOFError from exc

    return read


def session_ids() -> Callable[[], str]:
    counter = iter(range(1, 100))
    return lambda: f"sess-{next(counter)}"


def make_deps(
    lines: Iterable[str] | None = None,
    responder: FakeResponder | None = None,
    api_key: str | None = FAKE_KEY,
    env_path: Path | None = None,
    secrets: Iterable[str] = (),
) -> tuple[CliDeps, io.StringIO, FakeResponder]:
    output = io.StringIO()
    fake = responder or FakeResponder()
    secret_values = iter(secrets)
    deps = CliDeps(
        console=Console(file=output, width=200, color_system=None),
        responder_factory=lambda: fake,
        read_line=None if lines is None else line_reader(lines),
        read_secret=lambda prompt: next(secret_values),
        env_path=env_path or Path("/nonexistent/.env"),
        settings_factory=lambda: Settings(
            _env_file=None, google_api_key=SecretStr(api_key) if api_key else None
        ),
        new_session_id=session_ids(),
    )
    return deps, output, fake


@pytest.mark.dod("04.C1")
def test_chat_greets_and_shows_session_and_resume_hint():
    deps, output, _ = make_deps(lines=["/exit"])

    code = main([], deps)

    text = output.getvalue()
    assert code == 0
    assert "Lia" in text
    assert "sess-1" in text
    assert "--session sess-1" in text


@pytest.mark.dod("04.C1")
def test_new_command_starts_a_new_session():
    deps, output, fake = make_deps(lines=["oi", "/new", "tchau"])

    main([], deps)

    assert fake.calls == [("sess-1", "oi"), ("sess-2", "tchau")]
    assert "sess-2" in output.getvalue()


@pytest.mark.dod("04.C1")
def test_exit_command_ends_the_loop():
    deps, _, fake = make_deps(lines=["oi", "/exit", "nunca enviado"])

    code = main([], deps)

    assert code == 0
    assert fake.calls == [("sess-1", "oi")]


@pytest.mark.dod("04.C1")
def test_session_flag_resumes_given_session_id():
    deps, output, fake = make_deps(lines=["oi"])

    main(["--session", "antiga-42"], deps)

    assert fake.calls == [("antiga-42", "oi")]
    assert "antiga-42" in output.getvalue()


def test_reply_text_is_printed():
    deps, output, _ = make_deps(lines=["preço [violão]"])

    main([], deps)

    assert "eco: preço [violão]" in output.getvalue()


@pytest.mark.dod("04.C2")
def test_debug_prints_tools_tokens_and_latency():
    deps, output, _ = make_deps(lines=["oi"])

    main(["--debug"], deps)

    text = output.getvalue()
    assert "search_products, get_order" in text
    assert "321" in text
    assert "654 ms" in text


@pytest.mark.dod("04.C2")
def test_without_debug_no_turn_metrics_are_printed():
    deps, output, _ = make_deps(lines=["oi"])

    main([], deps)

    assert "search_products" not in output.getvalue()


@pytest.mark.dod("04.C3")
def test_missing_api_key_shows_friendly_message_and_exits_1():
    deps, output, fake = make_deps(lines=["oi"], api_key=None)

    code = main([], deps)

    text = output.getvalue()
    assert code == 1
    assert "https://aistudio.google.com/apikey" in text
    assert "uv run musical-agent setup" in text
    assert "Traceback" not in text
    assert fake.calls == []


@pytest.mark.dod("04.C3")
def test_rate_limit_error_shows_friendly_message_and_loop_continues():
    error = ClientError(429, {"error": {"message": "quota", "status": "RESOURCE_EXHAUSTED"}})
    deps, output, fake = make_deps(lines=["oi", "de novo"], responder=FakeResponder(error))

    code = main([], deps)

    text = output.getvalue()
    assert code == 0
    assert "muitas mensagens em pouco tempo" in text
    assert "RESOURCE_EXHAUSTED" not in text
    assert "Traceback" not in text
    assert len(fake.calls) == 2


@pytest.mark.dod("04.C3")
def test_other_api_error_shows_generic_friendly_message():
    error = ServerError(503, {"error": {"message": "down", "status": "UNAVAILABLE"}})
    deps, output, _ = make_deps(lines=["oi"], responder=FakeResponder(error))

    code = main([], deps)

    text = output.getvalue()
    assert code == 0
    assert "UNAVAILABLE" not in text
    assert "muitas mensagens" not in text
    assert "instabilidade" in text


def test_api_error_base_class_is_handled():
    deps, output, _ = make_deps(lines=["oi"], responder=FakeResponder(APIError(500, {})))

    assert main([], deps) == 0
    assert "Traceback" not in output.getvalue()


@pytest.mark.dod("04.C4")
def test_piped_stdin_runs_each_non_empty_line_and_exits_at_eof(monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("oi\n\n   \nquero um violão\n"))
    deps, _, fake = make_deps(lines=None)

    code = main([], deps)

    assert code == 0
    assert fake.calls == [("sess-1", "oi"), ("sess-1", "quero um violão")]


@pytest.mark.dod("04.C4")
def test_piped_stdin_honors_commands(monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("oi\n/new\nolá\n/exit\nignorado\n"))
    deps, _, fake = make_deps(lines=None)

    main(["--debug"], deps)

    assert fake.calls == [("sess-1", "oi"), ("sess-2", "olá")]


@pytest.mark.dod("04.C5")
def test_setup_creates_env_file_with_key_and_mode_600(tmp_path):
    env_path = tmp_path / ".env"
    deps, _, _ = make_deps(env_path=env_path, secrets=[FAKE_KEY])

    code = main(["setup"], deps)

    assert code == 0
    assert env_path.read_text().splitlines() == [
        f"GOOGLE_API_KEY={FAKE_KEY}",
        "GOOGLE_GENAI_USE_VERTEXAI=FALSE",
    ]
    assert stat.S_IMODE(env_path.stat().st_mode) == 0o600


@pytest.mark.dod("04.C5")
def test_setup_updates_existing_env_keeping_other_lines(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "MODEL=gemini-x\nGOOGLE_API_KEY=old\n# nota\nGOOGLE_GENAI_USE_VERTEXAI=TRUE\n"
    )
    env_path.chmod(0o644)
    deps, _, _ = make_deps(env_path=env_path, secrets=[FAKE_KEY])

    main(["setup"], deps)

    assert env_path.read_text().splitlines() == [
        "MODEL=gemini-x",
        f"GOOGLE_API_KEY={FAKE_KEY}",
        "# nota",
        "GOOGLE_GENAI_USE_VERTEXAI=FALSE",
    ]
    assert stat.S_IMODE(env_path.stat().st_mode) == 0o600


@pytest.mark.dod("04.C5")
def test_setup_never_prints_or_logs_the_key(tmp_path, caplog):
    deps, output, _ = make_deps(env_path=tmp_path / ".env", secrets=[FAKE_KEY])
    caplog.set_level(logging.DEBUG)

    main(["setup"], deps)

    assert FAKE_KEY not in output.getvalue()
    assert FAKE_KEY not in caplog.text
    assert "salva" in output.getvalue()


@pytest.mark.dod("04.C5")
def test_setup_rejects_empty_input_and_asks_again(tmp_path):
    env_path = tmp_path / ".env"
    deps, output, _ = make_deps(env_path=env_path, secrets=["", "   ", FAKE_KEY])

    code = main(["setup"], deps)

    assert code == 0
    assert "vazia" in output.getvalue()
    assert f"GOOGLE_API_KEY={FAKE_KEY}" in env_path.read_text()


@pytest.mark.dod("04.C5")
def test_setup_gives_up_after_repeated_empty_input(tmp_path):
    env_path = tmp_path / ".env"
    deps, _, _ = make_deps(env_path=env_path, secrets=["", "", ""])

    code = main(["setup"], deps)

    assert code == 1
    assert not env_path.exists()


def test_write_api_key_strips_surrounding_whitespace(tmp_path):
    env_path = tmp_path / ".env"

    write_api_key(env_path, f"  {FAKE_KEY}\n")

    assert env_path.read_text().splitlines()[0] == f"GOOGLE_API_KEY={FAKE_KEY}"
