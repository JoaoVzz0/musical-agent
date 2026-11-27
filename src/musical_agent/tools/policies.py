from __future__ import annotations

import logging

import httpx
from google.adk.tools import ToolContext
from google.genai.errors import APIError
from pypdf.errors import PyPdfError

from musical_agent.data.embeddings import load_embedding_index
from musical_agent.data.policies import load_policy_index
from musical_agent.types import PolicyPassage

logger = logging.getLogger(__name__)

DEFAULT_PASSAGES = 2
MIN_PASSAGES = 1
MAX_PASSAGES = 4
INDEX_UNAVAILABLE_MESSAGE = "Não foi possível consultar o manual de políticas da loja."


EMBEDDING_FAILURES = (APIError, httpx.HTTPError, OSError, ValueError)


def _clamp_passages(k: int) -> int:
    return max(MIN_PASSAGES, min(MAX_PASSAGES, k))


def _semantic_passages(question: str, k: int) -> list[PolicyPassage] | None:
    try:
        index = load_embedding_index()
        return None if index is None else index.search(question, k)
    except EMBEDDING_FAILURES as error:
        logger.warning("Embedding search unavailable, using BM25 (%s)", type(error).__name__)
        return None


def _rank_passages(question: str, k: int) -> list[PolicyPassage]:
    semantic = _semantic_passages(question, k)
    if semantic is not None:
        return semantic
    return load_policy_index().search(question, k=k)


def search_policies(
    question: str,
    k: int = DEFAULT_PASSAGES,
    tool_context: ToolContext | None = None,
) -> dict:
    """Search the store policies manual and return the most relevant sections.

    Use for store policy questions: opening hours, address and contacts, payment methods
    and installments, returns, exchanges, right of withdrawal, shipping and delivery
    times, order tracking, promotion rules, warranty and privacy. Do NOT use it for
    product prices, stock or order status; other tools answer those.

    Before searching, rewrite the customer's question with the manual's vocabulary, for
    example "dá pra parcelar?" -> "parcelamento cartão de crédito" and "me arrependi" ->
    "direito de arrependimento devolução". Answer only from the returned text and cite
    the section, for example "conforme a seção 4.1".

    Args:
        question: Search query in Portuguese, using the manual's vocabulary.
        k: Number of passages to return, from 1 to 4 (default 2).
        tool_context: Injected by the framework; not used.

    Returns:
        {"status": "ok", "passages": [{"section", "title", "text", "score"}, ...]} with
        the best passage first; {"status": "invalid_question"} when the question is
        blank; {"status": "error", "message": ...} when the manual cannot be read.
    """
    if not question or not question.strip():
        return {"status": "invalid_question"}
    try:
        passages = _rank_passages(question.strip(), _clamp_passages(k))
    except (OSError, ValueError, PyPdfError) as error:
        logger.error("Policy index unavailable: %s", error)
        return {"status": "error", "message": INDEX_UNAVAILABLE_MESSAGE}
    logger.info("Policy search returned sections %s", [p["section"] for p in passages])
    return {"status": "ok", "passages": passages}
