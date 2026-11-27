from __future__ import annotations

import importlib
import logging
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Protocol

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.plugins.base_plugin import BasePlugin
from google.genai import types

from musical_agent.config import Settings

logger = logging.getLogger(__name__)

PLUGIN_NAME = "safety"
MODEL_ARMOR_MODULE = "google.cloud.modelarmor_v1"
MODEL_ARMOR_MATCH = "MATCH_FOUND"
MODEL_ARMOR_REASON = "model_armor"
MODEL_ARMOR_FALLBACK_REASON = "model_armor_unavailable"
TEMPLATE_LOCATION_PATTERN = re.compile(r"/locations/([^/]+)/")

BLOCKED_INPUT_REPLY = (
    "Desculpe, não posso ajudar com esse pedido. Posso te ajudar a escolher um instrumento, "
    "consultar um pedido ou tirar dúvidas sobre as políticas da loja. Como posso ajudar?"
)
BLOCKED_OUTPUT_REPLY = (
    "Desculpe, não consigo compartilhar essa informação. Posso te ajudar com instrumentos, "
    "pedidos ou políticas da loja. O que você precisa?"
)

STORE_EMAIL_DOMAIN = "emporiodamusica.com.br"
STORE_PHONE_DIGITS = frozenset({"6733414444", "6733214500"})
BRAZIL_COUNTRY_CODE = "55"
LONGEST_NATIONAL_PHONE = 11

INPUT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "instruction_override",
        re.compile(
            r"\b(ignor\w*|esquec\w*|desconsider\w*|descart\w*|anul\w*)\s+"
            r"(todas\s+)?(as\s+|os\s+)?(suas\s+|seus\s+|tuas\s+|teus\s+)?"
            r"(\w+\s+)?(instruc\w*|regras|diretrizes|orientac\w*|comandos|prompt)\b"
            r"|\bignore\s+(all\s+)?(previous|prior|your)\s+instructions\b"
        ),
    ),
    (
        "role_play",
        re.compile(
            r"\b(finja|finge|fingir|faz de conta|faca de conta|aja como|atue como"
            r"|comporte-se como|se passe por|pretend|roleplay)\b"
            r"|\bvoce agora e\b|\ba partir de agora voce e\b"
            r"|\bnao (existem|ha|tem) (mais )?regras\b|\bsem (nenhuma )?regras\b"
        ),
    ),
    (
        "prompt_leak",
        re.compile(
            r"\b(prompt|instruc\w*|mensagem|configurac\w*) (de|do) sistema\b|\bsystem prompt\b"
            r"|\b(mostr|revel|repit|repet|exib|imprim|diga|cont[ae]|escrev|copi|list)\w*"
            r"\b.{0,30}\b(seu|sua|suas|seus|teu|tua|tuas|teus) "
            r"(prompt|instruc\w*|diretrizes|regras internas)\b"
        ),
    ),
    (
        "fake_authority",
        re.compile(
            r"\b(sou|eu sou|falo como|aqui e|quem fala e)\s+(o |a )?"
            r"(gerente|dono|dona|proprietari\w*|administrador\w*|admin|desenvolvedor\w*"
            r"|supervisor\w*|diretor\w*|funcionari\w*)\b.*\b(liber\w*|autoriz\w*|aprov\w*"
            r"|conced\w*|desbloque\w*|desconto|cupom|gratis|de graca)"
            r"|\b(gerente|dono|dona|diretor\w*|supervisor\w*)\s+(ja\s+)?(me\s+)?"
            r"(autorizou|liberou|aprovou)\b"
        ),
    ),
)

CPF_PATTERN = re.compile(r"(?<!\d)\d{3}\.?\d{3}\.?\d{3}-?\d{2}(?!\d)")
PHONE_WITH_AREA_CODE_PATTERN = re.compile(
    r"(?<![\d*])(?:\+?55[\s-]?)?\(?\d{2}\)?[\s-]?9?\d{4}[\s.-]?\d{4}(?![\d*])"
)
MOBILE_WITHOUT_AREA_CODE_PATTERN = re.compile(r"(?<![\d*])9\d{4}[\s.-]\d{4}(?![\d*])")
EMAIL_PATTERN = re.compile(r"[\w.+-]+@((?:[\w-]+\.)+[a-z]{2,})")


@dataclass(frozen=True)
class ScreeningResult:
    blocked: bool
    reason: str | None = None


ALLOWED = ScreeningResult(blocked=False)


class Screener(Protocol):
    def screen_input(self, text: str) -> ScreeningResult: ...

    def screen_output(self, text: str) -> ScreeningResult: ...


def normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    without_accents = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(without_accents.split())


def national_digits(phone: str) -> str:
    digits = re.sub(r"\D", "", phone)
    if len(digits) > LONGEST_NATIONAL_PHONE and digits.startswith(BRAZIL_COUNTRY_CODE):
        return digits[len(BRAZIL_COUNTRY_CODE) :]
    return digits


def contains_customer_phone(text: str) -> bool:
    if MOBILE_WITHOUT_AREA_CODE_PATTERN.search(text):
        return True
    return any(
        national_digits(match.group()) not in STORE_PHONE_DIGITS
        for match in PHONE_WITH_AREA_CODE_PATTERN.finditer(text)
    )


def is_store_domain(domain: str) -> bool:
    return domain == STORE_EMAIL_DOMAIN or domain.endswith(f".{STORE_EMAIL_DOMAIN}")


def contains_customer_email(text: str) -> bool:
    return any(not is_store_domain(match.group(1)) for match in EMAIL_PATTERN.finditer(text))


class LocalScreener:
    """Offline, pattern-based screener for pt-BR attacks and PII leaks.

    Args:
        protected_markers: Distinctive strings from the agent instruction; any response
            containing one of them is treated as a system prompt leak.
    """

    def __init__(self, protected_markers: tuple[str, ...] = ()) -> None:
        self._markers = tuple(normalize(marker) for marker in protected_markers if marker.strip())

    def screen_input(self, text: str) -> ScreeningResult:
        normalized = normalize(text)
        for reason, pattern in INPUT_PATTERNS:
            if pattern.search(normalized):
                return ScreeningResult(blocked=True, reason=reason)
        return ALLOWED

    def screen_output(self, text: str) -> ScreeningResult:
        normalized = normalize(text)
        if any(marker in normalized for marker in self._markers):
            return ScreeningResult(blocked=True, reason="prompt_leak")
        if CPF_PATTERN.search(normalized):
            return ScreeningResult(blocked=True, reason="pii_cpf")
        if contains_customer_phone(normalized):
            return ScreeningResult(blocked=True, reason="pii_phone")
        if contains_customer_email(normalized):
            return ScreeningResult(blocked=True, reason="pii_email")
        return ALLOWED


def model_armor_client_errors() -> tuple[type[BaseException], ...]:
    try:
        from google.api_core.exceptions import GoogleAPIError
    except ImportError:
        return (OSError,)
    return (OSError, GoogleAPIError)


def is_match_found(response: Any) -> bool:
    state = response.sanitization_result.filter_match_state
    candidates = (state, getattr(state, "name", None), getattr(state, "value", None))
    return MODEL_ARMOR_MATCH in candidates


class ModelArmorScreener:
    """Screener backed by Google Cloud Model Armor, layered on top of local screening.

    Args:
        template: Full Model Armor template name
            (`projects/<p>/locations/<l>/templates/<t>`).
        client: Optional pre-built client exposing `sanitize_user_prompt` and
            `sanitize_model_response`; built lazily from `google-cloud-modelarmor` if omitted.
        fallback: Local screener applied whenever Model Armor allows the text (defense in
            depth: Model Armor adds checks, never removes them) and alone when the library is
            missing or the API call fails; defaults to `LocalScreener()`.
    """

    def __init__(
        self, template: str, client: object | None = None, fallback: Screener | None = None
    ) -> None:
        self._template = template
        self._client = client
        self._fallback = fallback or LocalScreener()

    def screen_input(self, text: str) -> ScreeningResult:
        request = {"name": self._template, "user_prompt_data": {"text": text}}
        return self._sanitize("sanitize_user_prompt", request, self._fallback.screen_input, text)

    def screen_output(self, text: str) -> ScreeningResult:
        request = {"name": self._template, "model_response_data": {"text": text}}
        return self._sanitize(
            "sanitize_model_response", request, self._fallback.screen_output, text
        )

    def _sanitize(self, method: str, request: dict, fallback: Any, text: str) -> ScreeningResult:
        try:
            client = self._get_client()
            response = getattr(client, method)(request=request)
        except ImportError:
            logger.warning("safety: model armor library missing, using local screener")
            return fallback(text)
        except model_armor_client_errors() as error:
            logger.warning("safety: model armor call failed (%s)", type(error).__name__)
            return fallback(text)
        if is_match_found(response):
            return ScreeningResult(blocked=True, reason=MODEL_ARMOR_REASON)
        return fallback(text)

    def _get_client(self) -> Any:
        if self._client is None:
            self._client = build_model_armor_client(self._template)
        return self._client


def build_model_armor_client(template: str) -> Any:
    modelarmor = importlib.import_module(MODEL_ARMOR_MODULE)
    location = TEMPLATE_LOCATION_PATTERN.search(template)
    if location is None:
        return modelarmor.ModelArmorClient()
    endpoint = f"modelarmor.{location.group(1)}.rep.googleapis.com"
    return modelarmor.ModelArmorClient(client_options={"api_endpoint": endpoint})


def model_armor_installed() -> bool:
    try:
        importlib.import_module(MODEL_ARMOR_MODULE)
    except ImportError:
        return False
    return True


def build_screener(settings: Settings, protected_markers: tuple[str, ...] = ()) -> Screener:
    """Choose the screener for this deployment.

    Args:
        settings: App settings; `model_armor_template` enables Model Armor.
        protected_markers: Distinctive instruction strings blocked in model output.

    Returns:
        A `ModelArmorScreener` (with local fallback) when a template is configured and
        `google-cloud-modelarmor` is installed, otherwise a `LocalScreener`.
    """
    local = LocalScreener(protected_markers)
    if settings.model_armor_template and model_armor_installed():
        return ModelArmorScreener(settings.model_armor_template, fallback=local)
    return local


def text_of(content: types.Content | None) -> str:
    if content is None or not content.parts:
        return ""
    return "".join(part.text for part in content.parts if part.text and not part.thought)


def latest_user_text(llm_request: LlmRequest) -> str:
    for content in reversed(llm_request.contents or []):
        if content.role != "user":
            continue
        text = text_of(content)
        if text:
            return text
    return ""


def canned_response(text: str) -> LlmResponse:
    return LlmResponse(content=types.Content(role="model", parts=[types.Part(text=text)]))


class SafetyPlugin(BasePlugin):
    """Screens user input before the model and model output after it.

    Blocked turns get a friendly canned pt-BR reply instead of the model call or output.
    Only the reason category is logged; the blocked text is never echoed.

    Args:
        screener: Screening strategy; defaults to `LocalScreener()`.
    """

    def __init__(self, screener: Screener | None = None) -> None:
        super().__init__(name=PLUGIN_NAME)
        self._screener = screener or LocalScreener()

    async def before_model_callback(
        self, *, callback_context: CallbackContext, llm_request: LlmRequest
    ) -> LlmResponse | None:
        """Screen the latest user message; return the canned reply to skip the model."""
        text = latest_user_text(llm_request)
        if not text:
            return None
        result = self._screener.screen_input(text)
        if not result.blocked:
            return None
        logger.warning("safety: input blocked (reason=%s)", result.reason)
        return canned_response(BLOCKED_INPUT_REPLY)

    async def after_model_callback(
        self, *, callback_context: CallbackContext, llm_response: LlmResponse
    ) -> LlmResponse | None:
        """Screen the model's text; return the canned reply to replace a leaking response."""
        text = text_of(llm_response.content)
        if not text:
            return None
        result = self._screener.screen_output(text)
        if not result.blocked:
            return None
        logger.warning("safety: output blocked (reason=%s)", result.reason)
        return canned_response(BLOCKED_OUTPUT_REPLY)
