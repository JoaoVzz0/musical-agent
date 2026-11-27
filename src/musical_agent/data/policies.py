from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from pypdf import PdfReader
from rank_bm25 import BM25Okapi

from musical_agent.config import get_settings
from musical_agent.types import PolicyPassage

logger = logging.getLogger(__name__)

MANUAL_FILENAME = "store_policies.pdf"
COVER_PAGE_COUNT = 1
DEFAULT_TOP_K = 2
STEM_PREFIX_LENGTH = 5
FIRST_SECTION_NUMBER = 1

NOISE_LINE_PATTERNS = (
    re.compile(r"^P[áa]gina \d+$"),
    re.compile(r"^Empório da Música Manual de Políticas e Procedimentos$"),
    re.compile(r"^Empório da Música — Sua música começa aqui\.$"),
    re.compile(r"^Última atualização:"),
)
SECTION_HEADING = re.compile(r"^(?P<number>\d{1,2})\.\s+(?P<title>\S.*)$")
SUBSECTION_HEADING = re.compile(r"^(?P<section>\d{1,2})\.(?P<number>\d{1,2})\s+(?P<title>\S.*)$")
WORD = re.compile(r"[a-z0-9]+")

STOPWORDS = frozenset(
    {
        "a",
        "o",
        "as",
        "os",
        "um",
        "uma",
        "uns",
        "umas",
        "de",
        "da",
        "do",
        "das",
        "dos",
        "em",
        "na",
        "no",
        "nas",
        "nos",
        "por",
        "pela",
        "pelo",
        "pelas",
        "pelos",
        "para",
        "pra",
        "com",
        "sem",
        "e",
        "ou",
        "que",
        "se",
        "me",
        "te",
        "lhe",
        "eu",
        "voce",
        "voces",
        "ele",
        "ela",
        "eles",
        "elas",
        "vos",
        "meu",
        "minha",
        "seu",
        "sua",
        "seus",
        "suas",
        "qual",
        "quais",
        "quando",
        "como",
        "onde",
        "ao",
        "aos",
        "este",
        "esta",
        "isso",
        "isto",
        "esse",
        "essa",
        "ser",
        "foi",
        "sao",
        "tem",
        "ter",
        "ha",
        "mais",
        "muito",
        "posso",
        "pode",
        "podem",
        "vou",
        "quero",
        "gostaria",
        "sobre",
        "ja",
        "nao",
        "sim",
    }
)


@dataclass(frozen=True)
class PolicyChunk:
    section: str
    title: str
    text: str


@dataclass
class _Heading:
    section: str
    title: str
    lines: list[str]


def extract_manual_text(pdf_path: Path) -> str:
    """Extract the manual body text, dropping the cover page, page headers and footers.

    Args:
        pdf_path: Path to the store policies PDF.

    Returns:
        The cleaned text, one non-empty line per extracted line.
    """
    reader = PdfReader(pdf_path)
    body_pages = reader.pages[COVER_PAGE_COUNT:]
    lines = [line.strip() for page in body_pages for line in page.extract_text().splitlines()]
    return "\n".join(line for line in lines if line and not _is_noise(line))


def _is_noise(line: str) -> bool:
    return any(pattern.match(line) for pattern in NOISE_LINE_PATTERNS)


def split_into_chunks(text: str) -> list[PolicyChunk]:
    """Split the manual into one chunk per numbered section and subsection.

    Top-level headings are accepted only in sequence (1, 2, 3, ...) and subsections only
    under the current section, so numbered lists inside a section are kept as body text.
    A top-level section becomes a chunk only when it has its own intro text.

    Args:
        text: Cleaned manual text from `extract_manual_text`.

    Returns:
        Chunks in document order.
    """
    headings = _collect_headings(text.splitlines())
    return [
        PolicyChunk(section=heading.section, title=heading.title, text="\n".join(heading.lines))
        for heading in headings
        if heading.lines
    ]


def _collect_headings(lines: list[str]) -> list[_Heading]:
    headings: list[_Heading] = []
    next_section = FIRST_SECTION_NUMBER
    for line in lines:
        heading = _match_heading(line, next_section)
        if heading is not None:
            headings.append(heading)
            next_section += "." not in heading.section
        elif headings:
            headings[-1].lines.append(line)
    return headings


def _match_heading(line: str, next_section: int) -> _Heading | None:
    current_section = next_section - 1
    subsection = SUBSECTION_HEADING.match(line)
    if subsection and int(subsection["section"]) == current_section:
        section = f"{current_section}.{subsection['number']}"
        return _Heading(section=section, title=subsection["title"].strip(), lines=[])
    top_level = SECTION_HEADING.match(line)
    if top_level and int(top_level["number"]) == next_section:
        return _Heading(section=str(next_section), title=top_level["title"].strip(), lines=[])
    return None


def tokenize(text: str) -> list[str]:
    """Normalize text into BM25 terms.

    Lowercases, strips accents, drops pt-BR stopwords and truncates each word to a short
    prefix, a light stemmer that lets "arrependi" match "arrependimento".

    Args:
        text: Any Portuguese text.

    Returns:
        The list of normalized terms in order.
    """
    words = WORD.findall(_strip_accents(text.lower()))
    return [word[:STEM_PREFIX_LENGTH] for word in words if word not in STOPWORDS]


def _strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(char for char in decomposed if not unicodedata.combining(char))


class PolicyIndex:
    def __init__(self, chunks: list[PolicyChunk]) -> None:
        self._chunks = list(chunks)
        self._bm25 = BM25Okapi([tokenize(f"{chunk.title}\n{chunk.text}") for chunk in chunks])

    def chunks(self) -> list[PolicyChunk]:
        return list(self._chunks)

    def search(self, question: str, k: int = DEFAULT_TOP_K) -> list[PolicyPassage]:
        """Rank manual chunks against a question with BM25.

        Args:
            question: Customer question in Portuguese.
            k: Maximum number of passages to return.

        Returns:
            Up to `k` passages, best first, each with its BM25 score.
        """
        scores = self._bm25.get_scores(tokenize(question))
        ranked = sorted(range(len(self._chunks)), key=lambda i: scores[i], reverse=True)
        return [self._passage(position, float(scores[position])) for position in ranked[:k]]

    def _passage(self, position: int, score: float) -> PolicyPassage:
        chunk = self._chunks[position]
        return PolicyPassage(section=chunk.section, title=chunk.title, text=chunk.text, score=score)


@lru_cache(maxsize=1)
def load_policy_index(pdf_path: Path | None = None) -> PolicyIndex:
    path = pdf_path or get_settings().data_dir / MANUAL_FILENAME
    chunks = split_into_chunks(extract_manual_text(path))
    logger.info("Indexed %d policy chunks from %s", len(chunks), path)
    return PolicyIndex(chunks)
