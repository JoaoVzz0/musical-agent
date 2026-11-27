from __future__ import annotations

import re

import pytest

from musical_agent.config import PROJECT_ROOT

README_PATH = PROJECT_ROOT / "README.md"
REQUIRED_SECTIONS = (
    "Overview",
    "How to run",
    "Architecture",
    "Technical decisions",
    "Cost",
    "Data handling and assumptions",
    "Evaluation and gates",
    "Known limitations and next steps",
    "AI coding assistants",
)
MARKDOWN_LINK = re.compile(r"\]\(([^)#\s]+)(?:#[^)]*)?\)")


def readme() -> str:
    return README_PATH.read_text(encoding="utf-8")


@pytest.mark.dod("06.X1")
@pytest.mark.parametrize("section", REQUIRED_SECTIONS)
def test_readme_has_required_section(section):
    assert re.search(rf"^## {re.escape(section)}\s*$", readme(), flags=re.MULTILINE)


@pytest.mark.dod("06.X1")
def test_readme_has_no_unfilled_placeholders():
    assert "{{" not in readme()


@pytest.mark.dod("06.X2")
def test_every_relative_link_in_readme_exists():
    targets = [link for link in MARKDOWN_LINK.findall(readme()) if "://" not in link]

    missing = [link for link in targets if not (PROJECT_ROOT / link).exists()]

    assert targets
    assert missing == []
