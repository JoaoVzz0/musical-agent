from __future__ import annotations

import logging

from google.adk.tools import ToolContext
from pypdf.errors import PyPdfError

from musical_agent.data.policies import load_policy_index

logger = logging.getLogger(__name__)

DEFAULT_PASSAGES = 2
MIN_PASSAGES = 1
MAX_PASSAGES = 4
INDEX_UNAVAILABLE_MESSAGE = "Não foi possível consultar o manual de políticas da loja."


def _clamp_passages(k: int) -> int:
    return max(MIN_PASSAGES, min(MAX_PASSAGES, k))


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
        index = load_policy_index()
    except (OSError, ValueError, PyPdfError) as error:
        logger.error("Policy index unavailable: %s", error)
        return {"status": "error", "message": INDEX_UNAVAILABLE_MESSAGE}
    passages = index.search(question.strip(), k=_clamp_passages(k))
    logger.info("Policy search returned sections %s", [p["section"] for p in passages])
    return {"status": "ok", "passages": passages}
