from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from google.adk.agents import Agent, RunConfig
from google.adk.agents.invocation_context import LlmCallsLimitExceededError
from google.adk.apps import App
from google.adk.events import Event
from google.adk.models import BaseLlm
from google.adk.runners import Runner
from google.adk.sessions import BaseSessionService, DatabaseSessionService
from google.genai import types as genai_types

from musical_agent.agent.plugins.safety import (
    BLOCKED_INPUT_REPLY,
    BLOCKED_OUTPUT_REPLY,
    SafetyPlugin,
    build_screener,
)
from musical_agent.agent.prompt import PROTECTED_MARKERS, build_instruction
from musical_agent.config import PROJECT_ROOT, Settings, get_settings
from musical_agent.tools.catalog import get_product_details, search_products
from musical_agent.tools.orders import get_order_status
from musical_agent.tools.policies import search_policies
from musical_agent.tools.support import register_complaint
from musical_agent.types import AgentReply, ToolCallRecord

logger = logging.getLogger(__name__)

load_dotenv(PROJECT_ROOT / ".env")

APP_NAME = "musical_agent"
DEFAULT_USER_ID = "customer"
MILLISECONDS = 1000
SQLITE_URL_PREFIX = "sqlite+aiosqlite:///"
BLOCKED_REPLIES = (BLOCKED_INPUT_REPLY, BLOCKED_OUTPUT_REPLY)
MESSAGE_TOO_LONG_REPLY = (
    "Sua mensagem ficou um pouco longa para eu processar de uma vez. "
    "Pode resumir em poucas linhas o que você precisa?"
)
TURN_LIMIT_REPLY = (
    "Desculpe, não consegui concluir sua solicitação agora. "
    "Pode reformular a pergunta de um jeito mais direto?"
)
MODEL_TIMEOUT_MS = 60_000
MODEL_RETRY_ATTEMPTS = 3
TOOLS = [
    search_products,
    get_product_details,
    get_order_status,
    search_policies,
    register_complaint,
]


def model_call_config() -> genai_types.GenerateContentConfig:
    """Bound every model call: a hung connection fails after 60 s and is retried."""
    return genai_types.GenerateContentConfig(
        http_options=genai_types.HttpOptions(
            timeout=MODEL_TIMEOUT_MS,
            retry_options=genai_types.HttpRetryOptions(attempts=MODEL_RETRY_ATTEMPTS),
        )
    )


def build_agent(model: str | BaseLlm) -> Agent:
    return Agent(
        name=APP_NAME,
        model=model,
        description="Lia, assistente virtual da Empório da Música.",
        instruction=build_instruction,
        tools=TOOLS,
        generate_content_config=model_call_config(),
    )


def build_app(agent: Agent, settings: Settings) -> App:
    screener = build_screener(settings, PROTECTED_MARKERS)
    return App(name=APP_NAME, root_agent=agent, plugins=[SafetyPlugin(screener)])


def build_runner(app: App, session_service: BaseSessionService) -> Runner:
    return Runner(app=app, session_service=session_service)


def build_run_config(settings: Settings) -> RunConfig:
    return RunConfig(max_llm_calls=settings.max_llm_calls_per_turn)


def ensure_sqlite_dir(db_url: str) -> None:
    if db_url.startswith(SQLITE_URL_PREFIX):
        Path(db_url.removeprefix(SQLITE_URL_PREFIX)).parent.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def default_runner() -> Runner:
    settings = get_settings()
    ensure_sqlite_dir(settings.session_db_url)
    return build_runner(app, DatabaseSessionService(settings.session_db_url))


@dataclass
class TurnTrace:
    texts: list[str] = field(default_factory=list)
    calls: dict[str, genai_types.FunctionCall] = field(default_factory=dict)
    records: list[ToolCallRecord] = field(default_factory=list)
    tokens: int = 0

    def add(self, event: Event) -> None:
        if event.usage_metadata and event.usage_metadata.total_token_count:
            self.tokens += event.usage_metadata.total_token_count
        for call in event.get_function_calls():
            self.calls[call.id or call.name or ""] = call
        for response in event.get_function_responses():
            self._record(response)
        if event.is_final_response() and event.content and event.content.parts:
            self.texts.extend(part.text for part in event.content.parts if part.text)

    def _record(self, response: genai_types.FunctionResponse) -> None:
        call = self.calls.get(response.id or response.name or "")
        args = dict(call.args or {}) if call else {}
        name = response.name or (call.name if call else "") or ""
        self.records.append(ToolCallRecord(name=name, args=args, response=response.response))


async def ensure_session(runner: Runner, user_id: str, session_id: str) -> None:
    service = runner.session_service
    found = await service.get_session(
        app_name=runner.app_name, user_id=user_id, session_id=session_id
    )
    if found is None:
        await service.create_session(
            app_name=runner.app_name, user_id=user_id, session_id=session_id
        )


def build_reply(trace: TurnTrace, started: float, text: str | None = None) -> AgentReply:
    final_text = text if text is not None else "\n".join(trace.texts).strip()
    return AgentReply(
        text=final_text,
        tools_called=[record.name for record in trace.records],
        tool_calls=trace.records,
        tokens=trace.tokens,
        latency_ms=int((time.perf_counter() - started) * MILLISECONDS),
        blocked=final_text in BLOCKED_REPLIES,
    )


async def respond(
    session_id: str,
    message: str,
    user_id: str = DEFAULT_USER_ID,
    runner: Runner | None = None,
    settings: Settings | None = None,
) -> AgentReply:
    """Run one customer turn through the agent and summarize what happened.

    Rejects oversized messages before any model call, persists the conversation in the
    runner's session service and caps LLM calls per turn with ADK's `RunConfig`.
    """
    settings = settings or get_settings()
    started = time.perf_counter()
    trace = TurnTrace()
    if len(message) > settings.max_message_chars:
        return build_reply(trace, started, MESSAGE_TOO_LONG_REPLY)
    runner = runner or default_runner()
    await ensure_session(runner, user_id, session_id)
    content = genai_types.Content(role="user", parts=[genai_types.Part(text=message)])
    try:
        async for event in runner.run_async(
            user_id=user_id,
            session_id=session_id,
            new_message=content,
            run_config=build_run_config(settings),
        ):
            trace.add(event)
    except LlmCallsLimitExceededError:
        logger.warning("Turn stopped by llm_call_limit (%d calls)", settings.max_llm_calls_per_turn)
        return build_reply(trace, started, TURN_LIMIT_REPLY)
    return build_reply(trace, started)


root_agent = build_agent(get_settings().model)
app = build_app(root_agent, get_settings())
