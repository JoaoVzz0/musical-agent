from __future__ import annotations

import pytest

from musical_agent.config import PROJECT_ROOT

EXAMPLES_DIR = PROJECT_ROOT / "examples"
EXPECTED_FILES = (
    "01-violoes-ate-1000.md",
    "02-preco-takamine.md",
    "03-pedido-verificado.md",
    "04-arrependimento.md",
    "05-escopo-e-seguranca.md",
)
METADATA_FIELDS = ("Model", "AGENT_NOW", "Git", "not edited by hand")


def example_text(file_name: str) -> str:
    return (EXAMPLES_DIR / file_name).read_text(encoding="utf-8")


@pytest.mark.dod("05.B1")
def test_all_five_examples_exist():
    assert sorted(path.name for path in EXAMPLES_DIR.glob("*.md")) == list(EXPECTED_FILES)


@pytest.mark.dod("05.B1")
@pytest.mark.parametrize("file_name", EXPECTED_FILES)
def test_example_has_metadata_header_and_tools_per_turn(file_name):
    text = example_text(file_name)

    assert all(field in text for field in METADATA_FIELDS)
    assert text.count("Ferramentas chamadas") >= text.count("**Cliente:**") > 0


@pytest.mark.dod("05.B2")
def test_withdrawal_example_checks_the_order_and_the_policy():
    text = example_text("04-arrependimento.md")

    assert "get_order_status" in text
    assert "search_policies" in text
