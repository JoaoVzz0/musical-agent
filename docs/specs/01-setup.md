# Spec 01: Project setup

**Tracks:** single.

## Scope
- `pyproject.toml` (uv): `google-adk`, `google-genai`, `pandas`, `pypdf`, `rank-bm25`, `rapidfuzz`, `rich`, `pydantic-settings`, `python-dotenv`, `sqlalchemy` (+ the async SQLite driver the installed ADK version requires for `DatabaseSessionService`, e.g. `aiosqlite`); optional extra `modelarmor = ["google-cloud-modelarmor"]`; dev: `pytest`, `pytest-asyncio`, `ruff`, `pyyaml`, `numpy`. Ruff config (line length 100, isort).
- Package layout from spec 00 with `__init__.py` files; console script `musical-agent` (CLI). No API server (ADR-004).
- Copy challenge files into `data/` with simple names: `products.csv`, `categories.csv`, `customers.csv`, `orders.csv`, `order_items.csv`, `promotions.csv`, `store_policies.pdf`.
- `config.py` with `Settings` (pydantic-settings) and `.env.example` documenting every variable. `SESSION_DB_URL` defaults to `sqlite+aiosqlite:///var/sessions.db`; `var/` is created on startup if missing (no Docker, no server: ADK/SQLAlchemy creates the file and tables on first use). `.env.example` explains: create the key in Google AI Studio **in a project without billing** (free tier, zero cost; over the limit the API returns 429, never a bill).
- `types.py` with the TypedDict contracts from spec 00.
- `.gitignore` already exists (kit): keep it; add entries only if setup creates new local artifacts.
- `docs/decisions.md` with:
  - ADR-001: Google ADK + Gemini 2.5 Flash (free tier, native function calling, sessions, plugins, `adk web`).
  - ADR-002: hybrid architecture, function calling for data + RAG for policies (over a SQL agent: data is small, rules must be deterministic and authorization must live in code).
  - ADR-003: policy RAG with section chunks + BM25 (provisional; confirmed or changed by the retrieval eval in phase 05). Compares: full manual in the prompt, BM25, embeddings, hybrid.
  - ADR-004: CLI + `adk web`, no custom REST API and in-process function calling, **due to the prototype's scope**. A real project would need an API for scale (auth, rate limiting, stateless workers, channel webhooks) and tools exposed via MCP servers instead of in-process tool calling (reasons in spec 06).
  - ADR-005: guardrails, local screening by default and Model Armor optional (needs a GCP project with billing).
  - ADR-006: sessions on SQLite via `DatabaseSessionService`, **due to the prototype's scope** (zero infra for the reviewer, offline tests). A real project would use `FirestoreSessionService` or `VertexAiSessionService` (Agent Engine) or Postgres on Cloud SQL; the swap is one line because the `Runner` depends on `BaseSessionService`.
- README skeleton with final section headings.
- **Comment check:** `scripts/check_comments.py` scans `src/`, `tests/`, `evals/` and `scripts/` with `tokenize` and exits non-zero on any `#` comment except tool directives (`# noqa`, `# type: ignore`, `# pragma: no cover`) and a first-line shebang; prints `file:line` for each violation.
- **DoD tooling:** register pytest markers `dod(id)` and `evals` in `pyproject.toml` (`--strict-markers`); `scripts/dod_check.py` takes phase numbers (`02`) or track ids (`02.A 03.D`), parses the DoD tables of `docs/specs/NN-*.md`, collects `@pytest.mark.dod("...")` markers (one or more ids per marker) from `tests/` and `evals/`, and exits non-zero listing every `test` row without a test. `--done` checks every track marked `done` in `STATUS.md` (used by CI).

## DoD
| ID | Criterion | Verified by |
|---|---|---|
| 01.X1 | `uv sync` succeeds from a clean clone | command: `uv sync` |
| 01.X2 | `Settings` loads defaults (incl. `SESSION_DB_URL` under `var/`) and reads overrides from env (`MODEL`, `MAX_LLM_CALLS_PER_TURN`, `AGENT_NOW`) | test |
| 01.X3 | `types.py` TypedDicts have exactly the keys of the contracts in spec 00 | test |
| 01.X4 | Challenge files exist in `data/` with the simple names | test |
| 01.X5 | `.gitignore` covers `.env`/`.env.*` (but not `.env.example`), credential files, `*.db`, `var/`, `.adk/`, `evals/.cache/`, `challenge/`, `HOW_TO_USE.md` | test (uses `git check-ignore`) |
| 01.X6 | `dod_check.py` reports a missing test row and passes when all rows are covered (fixture spec in `tmp_path`) | test |
| 01.X7 | `uv run pytest` green and `uv run ruff check .` / `ruff format --check .` clean | command |
| 01.X8 | ADR-001..006 present in `docs/decisions.md`, each with context, decision, consequences | manual: reason, prose quality is a review item |
| 01.X9 | `check_comments.py` flags inline and full-line comments and accepts docstrings, `# noqa`, `# type: ignore`, `# pragma: no cover` and a shebang (fixture files in `tmp_path`) | test |

## Commits
- `chore: scaffold project with uv and google adk`
- `test: add dod traceability check and setup tests`
- `docs: add specs, rules, initial adrs and readme skeleton`
