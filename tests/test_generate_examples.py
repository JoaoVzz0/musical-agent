from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from google.genai.errors import ClientError, ServerError

from musical_agent.config import PROJECT_ROOT
from musical_agent.types import AgentReply, ToolCallRecord

SCRIPT_PATH = PROJECT_ROOT / "scripts" / "generate_examples.py"
EXPECTED_FILE_NAMES = [
    "01-violoes-ate-1000.md",
    "02-preco-takamine.md",
    "03-pedido-verificado.md",
    "04-arrependimento.md",
    "05-escopo-e-seguranca.md",
]


def load_script():
    spec = importlib.util.spec_from_file_location("generate_examples", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["generate_examples"] = module
    spec.loader.exec_module(module)
    return module


gen = load_script()


def make_reply(text: str = "Olá!", tools: list[str] | None = None, blocked: bool = False):
    tools = tools or []
    return AgentReply(
        text=text,
        tools_called=tools,
        tool_calls=[ToolCallRecord(name=name, args={}, response=None) for name in tools],
        tokens=10,
        latency_ms=5,
        blocked=blocked,
    )


class FakeResponder:
    def __init__(self, outcomes=None):
        self.outcomes = list(outcomes or [])
        self.calls: list[tuple[str, str]] = []

    async def __call__(self, session_id: str, message: str) -> AgentReply:
        self.calls.append((session_id, message))
        outcome = self.outcomes.pop(0) if self.outcomes else make_reply()
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FakeSleep:
    def __init__(self):
        self.calls: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


def rate_limited() -> ClientError:
    return ClientError(429, {"error": {"message": "quota", "status": "RESOURCE_EXHAUSTED"}}, None)


def overloaded() -> ServerError:
    return ServerError(503, {"error": {"message": "overloaded", "status": "UNAVAILABLE"}}, None)


def sample_metadata():
    return gen.Metadata(
        model="gemini-test",
        agent_now="2026-03-25T10:00:00-04:00",
        git_hash="abc1234",
        generated_at="2026-11-27T12:00:00+00:00",
    )


def two_turn_conversation():
    return gen.ExampleConversation(
        file_name="99-teste.md",
        title="Teste",
        scenario="Cenário de teste.",
        turns=("Primeira pergunta?", "Segunda pergunta?"),
    )


def test_conversations_are_exactly_the_five_listed_files():
    names = [conversation.file_name for conversation in gen.CONVERSATIONS]

    assert names == EXPECTED_FILE_NAMES


def test_withdrawal_conversation_includes_order_number_and_email():
    conversation = gen.CONVERSATIONS[3]

    joined = " ".join(conversation.turns)

    assert "pedido 7" in joined
    assert "leticia.rocha@jmail.com" in joined


@pytest.mark.dod("05.B1")
def test_render_markdown_includes_metadata_header():
    turns = [gen.TurnRecord(message="Oi", reply=make_reply())]

    rendered = gen.render_markdown(two_turn_conversation(), turns, sample_metadata())

    assert rendered.startswith("# Teste")
    assert "gemini-test" in rendered
    assert "2026-03-25T10:00:00-04:00" in rendered
    assert "abc1234" in rendered
    assert "responses are not edited by hand" in rendered


@pytest.mark.dod("05.B1")
def test_render_markdown_lists_tools_per_turn_or_none():
    turns = [
        gen.TurnRecord(message="A", reply=make_reply(tools=["search_products", "get_product"])),
        gen.TurnRecord(message="B", reply=make_reply()),
    ]

    rendered = gen.render_markdown(two_turn_conversation(), turns, sample_metadata())

    assert "search_products, get_product" in rendered
    assert "nenhuma" in rendered


def test_render_markdown_reports_blocked_turns():
    turns = [gen.TurnRecord(message="A", reply=make_reply(blocked=True))]

    rendered = gen.render_markdown(two_turn_conversation(), turns, sample_metadata())

    assert "Bloqueado pelo plugin de segurança: sim" in rendered


def test_render_markdown_keeps_reply_text_verbatim():
    reply_text = "Temos **duas** opções:\n\n- Violão A: R$ 899,00\n- Violão B: R$ 999,90"
    turns = [gen.TurnRecord(message="Quais?", reply=make_reply(text=reply_text))]

    rendered = gen.render_markdown(two_turn_conversation(), turns, sample_metadata())

    assert reply_text in rendered
    assert "Quais?" in rendered


async def test_run_conversation_sleeps_between_turns_only():
    responder, sleep = FakeResponder(), FakeSleep()

    turns = await gen.run_conversation(two_turn_conversation(), responder, sleep, 7)

    assert [turn.message for turn in turns] == ["Primeira pergunta?", "Segunda pergunta?"]
    assert sleep.calls == [7]


async def test_run_conversation_uses_one_session_for_all_turns():
    responder = FakeResponder()

    await gen.run_conversation(two_turn_conversation(), responder, FakeSleep(), 0)

    session_ids = {session_id for session_id, _ in responder.calls}
    assert len(session_ids) == 1
    assert session_ids.pop().startswith("examples-99-teste-")


async def test_rate_limit_then_success_retries_the_same_turn():
    responder = FakeResponder([rate_limited(), make_reply(text="ok")])
    sleep = FakeSleep()
    single_turn = gen.ExampleConversation("99-teste.md", "T", "S", ("Pergunta?",))

    turns = await gen.run_conversation(single_turn, responder, sleep, 7)

    assert [message for _, message in responder.calls] == ["Pergunta?", "Pergunta?"]
    assert turns[0].reply.text == "ok"
    assert sleep.calls == [gen.RETRY_DELAYS_S[0]]


async def test_overloaded_model_is_also_retried():
    responder = FakeResponder([overloaded(), make_reply(text="ok")])
    single_turn = gen.ExampleConversation("99-teste.md", "T", "S", ("Pergunta?",))

    turns = await gen.run_conversation(single_turn, responder, FakeSleep(), 0)

    assert turns[0].reply.text == "ok"


async def test_persistent_rate_limit_raises_clear_error():
    attempts = len(gen.RETRY_DELAYS_S) + 1
    responder = FakeResponder([rate_limited() for _ in range(attempts)])
    sleep = FakeSleep()
    single_turn = gen.ExampleConversation("99-teste.md", "T", "S", ("Pergunta?",))

    with pytest.raises(gen.GenerationError, match="99-teste.md"):
        await gen.run_conversation(single_turn, responder, sleep, 0)

    assert len(responder.calls) == attempts
    assert sleep.calls == list(gen.RETRY_DELAYS_S)


async def test_non_retryable_api_error_is_not_retried():
    responder = FakeResponder([ClientError(400, {"error": {"message": "bad"}}, None)])
    single_turn = gen.ExampleConversation("99-teste.md", "T", "S", ("Pergunta?",))

    with pytest.raises(ClientError):
        await gen.run_conversation(single_turn, responder, FakeSleep(), 0)

    assert len(responder.calls) == 1


async def test_generate_writes_one_file_per_conversation(tmp_path: Path):
    conversations = (two_turn_conversation(), gen.CONVERSATIONS[0])

    written = await gen.generate(
        conversations, FakeResponder(), tmp_path, sample_metadata(), FakeSleep(), 0
    )

    assert sorted(path.name for path in written) == ["01-violoes-ate-1000.md", "99-teste.md"]
    assert (tmp_path / "99-teste.md").read_text(encoding="utf-8").startswith("# Teste")


async def test_generate_sleeps_between_conversations(tmp_path: Path):
    single_turn = gen.ExampleConversation("98-a.md", "A", "S", ("Oi",))
    other_turn = gen.ExampleConversation("99-b.md", "B", "S", ("Oi",))
    sleep = FakeSleep()

    await gen.generate(
        (single_turn, other_turn), FakeResponder(), tmp_path, sample_metadata(), sleep, 5
    )

    assert sleep.calls == [5]


def test_select_conversations_by_prefix():
    selected = gen.select_conversations(gen.CONVERSATIONS, "04")

    assert [conversation.file_name for conversation in selected] == ["04-arrependimento.md"]


def test_select_conversations_rejects_unknown_prefix():
    with pytest.raises(gen.GenerationError, match="99"):
        gen.select_conversations(gen.CONVERSATIONS, "99")


def test_main_only_flag_writes_single_conversation(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("AGENT_NOW", "")
    responder, sleep = FakeResponder(), FakeSleep()

    exit_code = gen.main(
        ["--only", "04", "--turn-delay", "1", "--output-dir", str(tmp_path)],
        responder=responder,
        sleep=sleep,
    )

    assert exit_code == 0
    assert [path.name for path in tmp_path.iterdir()] == ["04-arrependimento.md"]
    assert len(responder.calls) == len(gen.CONVERSATIONS[3].turns)
    assert sleep.calls == [1, 1]


def test_main_pins_agent_clock_in_metadata(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("AGENT_NOW", "")

    gen.main(["--only", "01", "--output-dir", str(tmp_path)], FakeResponder(), FakeSleep())

    rendered = (tmp_path / "01-violoes-ate-1000.md").read_text(encoding="utf-8")
    assert gen.AGENT_NOW in rendered


def test_main_returns_error_code_when_generation_fails(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("AGENT_NOW", "")
    responder = FakeResponder([rate_limited() for _ in range(len(gen.RETRY_DELAYS_S) + 1)])

    exit_code = gen.main(["--only", "01", "--output-dir", str(tmp_path)], responder, FakeSleep())

    assert exit_code == 1


def test_git_short_hash_tolerates_missing_git(monkeypatch):
    def broken_run(*args, **kwargs):
        raise FileNotFoundError("git")

    monkeypatch.setattr(gen.subprocess, "run", broken_run)

    assert gen.git_short_hash() == "unknown"
