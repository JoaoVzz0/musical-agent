from __future__ import annotations

import argparse
import asyncio
import getpass
import importlib
import logging
import os
import sys
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Protocol

from google.genai.errors import APIError
from rich.console import Console
from rich.text import Text

from musical_agent.config import PROJECT_ROOT, Settings, get_settings
from musical_agent.types import AgentReply

AGENT_MODULE = "musical_agent.agent.agent"
API_KEY_VARIABLE = "GOOGLE_API_KEY"
BACKEND_VARIABLE = "GOOGLE_GENAI_USE_ENTERPRISE"
ENTERPRISE_DISABLED = "FALSE"
ENV_FILE_MODE = 0o600
RATE_LIMIT_STATUS = 429
MAX_KEY_ATTEMPTS = 3
EXIT_OK = 0
EXIT_ERROR = 1
NEW_COMMAND = "/new"
EXIT_COMMAND = "/exit"
USER_PROMPT = "Você: "
SETUP_COMMAND = "setup"
API_KEY_URL = "https://aistudio.google.com/apikey"
LOG_FILE_NAME = "musical-agent.log"
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"

GREETING = (
    "Olá! Eu sou a Lia, assistente virtual do Empório da Música. "
    "Posso ajudar com produtos, preços, pedidos, trocas e políticas da loja."
)
COMMANDS_HINT = f"Comandos: {NEW_COMMAND} inicia uma nova conversa, {EXIT_COMMAND} encerra."
MISSING_KEY_MESSAGE = (
    "Não encontrei a chave da API do Gemini (GOOGLE_API_KEY).\n"
    f"Gere uma chave gratuita em {API_KEY_URL} e configure com:\n"
    "  uv run musical-agent setup"
)
RATE_LIMIT_MESSAGE = (
    "Lia: Recebi muitas mensagens em pouco tempo. Tente de novo em instantes, por favor."
)
API_FAILURE_MESSAGE = (
    "Lia: Estou com uma instabilidade para responder agora. Tente de novo em instantes, por favor."
)
GOODBYE = "Lia: Obrigada pelo contato! Até a próxima."
KEY_PROMPT = "Cole sua GOOGLE_API_KEY (a digitação fica oculta): "
EMPTY_KEY_MESSAGE = "A chave não pode ficar vazia. Tente novamente."
SETUP_FAILED_MESSAGE = "Nenhuma chave informada. Rode `uv run musical-agent setup` de novo."


class Responder(Protocol):
    def __call__(
        self, session_id: str, message: str, user_id: str = ...
    ) -> Awaitable[AgentReply]: ...


def load_default_responder() -> Responder:
    """Import the real agent only when a chat starts, so the CLI loads without it."""
    return importlib.import_module(AGENT_MODULE).respond


def new_session_id() -> str:
    return uuid.uuid4().hex


@dataclass
class CliDeps:
    console: Console = field(default_factory=Console)
    responder_factory: Callable[[], Responder] = load_default_responder
    read_line: Callable[[], str] | None = None
    read_secret: Callable[[str], str] = getpass.getpass
    env_path: Path = PROJECT_ROOT / ".env"
    settings_factory: Callable[[], Settings] = get_settings
    new_session_id: Callable[[], str] = new_session_id


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="musical-agent", description="Atendimento do Empório da Música com a Lia."
    )
    parser.add_argument("--session", help="retoma a conversa com este id de sessão")
    parser.add_argument(
        "--debug", action="store_true", help="mostra ferramentas, tokens e latência"
    )
    subcommands = parser.add_subparsers(dest="command")
    subcommands.add_parser(SETUP_COMMAND, help="salva a GOOGLE_API_KEY no arquivo .env")
    return parser


def configure_logging(log_path: Path) -> None:
    """Send every log record, including library stack traces, to a file.

    The terminal is the customer's chat window: only Lia's replies belong there.
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(log_path, encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT, handlers=[handler], force=True)
    logging.captureWarnings(True)


def main(argv: list[str] | None = None, deps: CliDeps | None = None) -> int:
    args = build_parser().parse_args(argv)
    if deps is None:
        deps = CliDeps()
        configure_logging(deps.settings_factory().support_dir / LOG_FILE_NAME)
    if args.command == SETUP_COMMAND:
        return run_setup(deps)
    return run_chat(deps, session_id=args.session, debug=args.debug)


def has_api_key(settings: Settings) -> bool:
    key = settings.google_api_key
    return key is not None and bool(key.get_secret_value().strip())


def run_chat(deps: CliDeps, session_id: str | None, debug: bool) -> int:
    console = deps.console
    if not has_api_key(deps.settings_factory()):
        console.print(Text(MISSING_KEY_MESSAGE))
        return EXIT_ERROR
    read_line = deps.read_line or default_line_reader(console)
    responder = deps.responder_factory()
    return asyncio.run(chat_loop(deps, responder, read_line, session_id, debug))


def default_line_reader(console: Console) -> Callable[[], str]:
    if sys.stdin.isatty():
        return lambda: console.input(USER_PROMPT)
    return piped_line_reader(sys.stdin, console)


def piped_line_reader(stream: IO[str], console: Console) -> Callable[[], str]:
    def read() -> str:
        line = stream.readline()
        if not line:
            raise EOFError
        if line.strip():
            console.print(Text(f"{USER_PROMPT}{line.strip()}"))
        return line

    return read


async def chat_loop(
    deps: CliDeps,
    responder: Responder,
    read_line: Callable[[], str],
    session_id: str | None,
    debug: bool,
) -> int:
    console = deps.console
    console.print(Text(f"Lia: {GREETING}"))
    session_id = announce_session(console, session_id or deps.new_session_id(), session_id)
    console.print(Text(COMMANDS_HINT))
    while (message := next_message(read_line)) is not None:
        if message == EXIT_COMMAND:
            break
        if message == NEW_COMMAND:
            session_id = announce_session(console, deps.new_session_id(), None)
            continue
        await run_turn(console, responder, session_id, message, debug)
    console.print(Text(GOODBYE))
    return EXIT_OK


def announce_session(console: Console, session_id: str, resumed_id: str | None) -> str:
    action = "Retomando a sessão" if resumed_id else "Sessão"
    console.print(Text(f"{action}: {session_id}"))
    console.print(Text(f"Para retomar depois: uv run musical-agent --session {session_id}"))
    return session_id


def next_message(read_line: Callable[[], str]) -> str | None:
    while True:
        try:
            message = read_line().strip()
        except (EOFError, KeyboardInterrupt):
            return None
        if message:
            return message


async def run_turn(
    console: Console, responder: Responder, session_id: str, message: str, debug: bool
) -> None:
    try:
        reply = await responder(session_id, message)
    except APIError as error:
        console.print(Text(api_error_message(error)))
        return
    console.print(Text(f"Lia: {reply.text}"))
    if debug:
        console.print(Text(debug_line(reply), style="dim"))


def api_error_message(error: APIError) -> str:
    if error.code == RATE_LIMIT_STATUS:
        return RATE_LIMIT_MESSAGE
    return API_FAILURE_MESSAGE


def debug_line(reply: AgentReply) -> str:
    tools = ", ".join(reply.tools_called) or "nenhuma"
    return (
        f"[debug] ferramentas: {tools} | tokens: {reply.tokens} | "
        f"latência: {reply.latency_ms} ms | bloqueado: {'sim' if reply.blocked else 'não'}"
    )


def run_setup(deps: CliDeps) -> int:
    key = ask_api_key(deps)
    if key is None:
        deps.console.print(Text(SETUP_FAILED_MESSAGE))
        return EXIT_ERROR
    write_api_key(deps.env_path, key)
    deps.console.print(Text(f"Chave salva em {deps.env_path}. Agora rode: uv run musical-agent"))
    return EXIT_OK


def ask_api_key(deps: CliDeps) -> str | None:
    for _ in range(MAX_KEY_ATTEMPTS):
        key = deps.read_secret(KEY_PROMPT).strip()
        if key:
            return key
        deps.console.print(Text(EMPTY_KEY_MESSAGE))
    return None


def write_api_key(env_path: Path, key: str) -> None:
    """Set the API key and disable Vertex AI in the env file, keeping every other line."""
    existing = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    updates = {API_KEY_VARIABLE: key.strip(), BACKEND_VARIABLE: ENTERPRISE_DISABLED}
    lines = [replace_assignment(line, updates) for line in existing]
    assigned = {variable_name(line) for line in existing}
    lines.extend(f"{name}={value}" for name, value in updates.items() if name not in assigned)
    write_private_file(env_path, "\n".join(lines) + "\n")


def variable_name(line: str) -> str:
    return line.split("=", 1)[0].strip() if "=" in line else ""


def replace_assignment(line: str, updates: dict[str, str]) -> str:
    name = variable_name(line)
    return f"{name}={updates[name]}" if name in updates else line


def write_private_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, ENV_FILE_MODE)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(content)
    path.chmod(ENV_FILE_MODE)
