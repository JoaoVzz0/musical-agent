from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

JUDGE_MODEL = "gemini-3.1-flash-lite"
JUDGE_TEMPERATURE = 0.0
JSON_MIME_TYPE = "application/json"
CODE_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)

JUDGE_INSTRUCTIONS = """You are a strict evaluator of a customer service conversation for a \
musical instrument store. The agent speaks Brazilian Portuguese.
Judge ONLY against the rubric below. Use the tool outputs as the source of truth for prices, \
stock, orders and policies. Do not reward or penalize anything outside the rubric.
Answer with a single JSON object and nothing else: {"passed": true|false, "reason": "<one \
short sentence>"}."""

Generate = Callable[[str], str]
Turn = tuple[str, str]


@dataclass(frozen=True)
class Verdict:
    passed: bool
    reason: str


def _format_conversation(conversation: Sequence[Turn]) -> str:
    return "\n".join(f"[{role}] {text}" for role, text in conversation)


def build_prompt(
    conversation: Sequence[Turn], tool_outputs: Sequence[dict[str, Any]], criteria: str
) -> str:
    tools_json = "\n".join(json.dumps(output, ensure_ascii=False) for output in tool_outputs)
    return (
        f"{JUDGE_INSTRUCTIONS}\n\n## Conversation\n{_format_conversation(conversation)}\n\n"
        f"## Tool outputs\n{tools_json or '(no tools called)'}\n\n## Rubric\n{criteria}\n"
    )


def _malformed(raw: str) -> Verdict:
    logger.warning("judge returned malformed output: %.200s", raw)
    return Verdict(passed=False, reason=f"malformed judge output: {raw[:200]!r}")


def parse_verdict(raw: str) -> Verdict:
    text = raw.strip()
    fenced = CODE_FENCE.match(text)
    if fenced:
        text = fenced.group(1)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return _malformed(raw)
    if not isinstance(data, dict):
        return _malformed(raw)
    passed, reason = data.get("passed"), data.get("reason")
    if not isinstance(passed, bool) or not isinstance(reason, str):
        return _malformed(raw)
    return Verdict(passed=passed, reason=reason)


class Judge:
    """LLM judge for the rubric layer; the model call is injected so tests use a fake."""

    def __init__(self, generate: Generate) -> None:
        self._generate = generate

    def evaluate(
        self,
        conversation: Sequence[Turn],
        tool_outputs: Sequence[dict[str, Any]],
        criteria: str,
    ) -> Verdict:
        prompt = build_prompt(conversation, tool_outputs, criteria)
        return parse_verdict(self._generate(prompt))


def default_generate(model: str = JUDGE_MODEL) -> Generate:
    """Build a `generate` backed by google-genai (temperature 0, JSON output).

    The client is created lazily so importing this module needs no API key.
    """
    from google import genai
    from google.genai import types

    client = genai.Client()
    config = types.GenerateContentConfig(
        temperature=JUDGE_TEMPERATURE, response_mime_type=JSON_MIME_TYPE
    )

    def generate(prompt: str) -> str:
        response = client.models.generate_content(model=model, contents=prompt, config=config)
        return response.text or ""

    return generate
