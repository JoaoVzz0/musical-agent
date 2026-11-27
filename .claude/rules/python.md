---
paths:
  - "src/**/*.py"
  - "tests/**/*.py"
  - "evals/**/*.py"
  - "scripts/**/*.py"
---

# Python rules

## Code design
- **Single Responsibility:** one module = one concern (loading data, pricing rules, order lookup, CLI rendering). Functions do one thing and stay under ~30 lines; extract helpers instead of nesting.
- **Clean Code:** intention-revealing names, no magic numbers (business constants live in `domain/rules.py`), no dead code, no commented-out code, early returns over deep `if` nesting.
- **Pure business logic:** pricing, installments, promotions and after-sales window rules are pure functions with no I/O, so they are trivially testable.
- **Layers:** `data` (I/O) -> `domain` (rules) -> `tools` (agent-facing adapters) -> `agent` -> `interfaces` (CLI; no custom API, see ADR-004). Lower layers never import upper layers.
- **Dependency injection:** pass the dataset/index as arguments or via a small provider; no hidden globals except cached loaders.

## Typing and docs
- Type hints on every public function; `from __future__ import annotations`.
- **Docstrings (Google style), only where they carry information:** one-line summary, `Args`, `Returns`, `Raises` when relevant.
  - **Required** on every agent tool (the LLM reads them: say *when* to use the tool, the arguments and what it returns) and on non-obvious public entry points (plugin hooks, `respond()`, business rules whose source in the manual is not evident from the name).
  - **Not written** on simple, self-explanatory functions; a docstring that repeats the name is noise.

## Comments (strict)
- **Never** write `#` comments in Python code: no inline comments, no comments above lines, no section banners, no commented-out code, no TODOs.
- Code explains itself through names, small functions and named constants. If a block needs a comment, extract a well-named function or constant instead.
- The only documentation inside code is the docstring, used as described above.
- Allowed `#` lines are tool directives only: `# noqa: <code>`, `# type: ignore[<code>]`, `# pragma: no cover`, and a shebang in scripts.
- Enforced by `scripts/check_comments.py` (CI and every wave verification).
- Return contracts use `TypedDict` or Pydantic models from `types.py`; never return bare tuples across layers.

## Configuration and errors
- Settings via `pydantic-settings` (`config.py`), loaded from `.env`; never hardcode keys. `.env` is git-ignored, `.env.example` documents every variable.
- Catch specific exceptions only; tools never raise to the agent, they return `{"status": "error", "message": ...}`.
- Structured logging with `logging` (no `print` outside the CLI renderer).

## Tests (TDD driven by the DoD)
- Every `test` row of a phase DoD has at least one test marked `@pytest.mark.dod("PP.Tn")`; tests are written before the code and seen failing first.
- A test may cover several DoD IDs (`@pytest.mark.dod("02.C1", "02.C2")`); a DoD ID may need several tests.
- Tests outside the DoD are welcome (edge cases found while coding) and need no marker.

## Quality gates
- `uv run ruff check .` and `uv run ruff format --check .` clean.
- `uv run pytest tests/` green; deterministic tests never call an LLM.
- `uv run python scripts/dod_check.py NN` passes for the phase being delivered.
- Tests follow Arrange-Act-Assert, one behavior per test, descriptive names (`test_pix_discount_not_applied_on_promotional_price`).
