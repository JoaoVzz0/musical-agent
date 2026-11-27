# Empório da Música: Customer Service Agent

Technical challenge (Artefact, AI Engineer). Text-based customer service agent in Python with Google ADK + Gemini.
The agent talks to customers in **Brazilian Portuguese**; code, docs, specs and commits are in **English**.

## Rules
Rules live in `.claude/rules/` (`python.md`, `agent.md`, `evals.md`, `security.md`) and load automatically for matching files.

## Workflow
- Specs live in `docs/specs/`, organized by phase (what to build). Execution follows `docs/specs/PLAN.md`, organized by waves (sequential) and lanes (parallel); a wave starts only when the tracks it depends on are `done` in `docs/specs/STATUS.md`.
- Decisions and assumptions go to `docs/decisions.md` (short ADR: context, decision, consequences).
- **TDD driven by the DoD:** every DoD row has an ID; `test` rows get a test marked `@pytest.mark.dod("<ID>")`, written and seen failing before the code. `scripts/dod_check.py` enforces the mapping.
- Implement with the `implement-wave` skill.

## Comments
- **Never** write `#` comments in code (inline, above lines, banners, commented-out code, TODOs). Functions must be self-explanatory through names and small functions.
- Docstrings (Google style) only where they carry information: always on agent tools (read by the LLM), and on complex or non-obvious public functions. Nothing else.
- Enforced by `scripts/check_comments.py`; details in `.claude/rules/python.md`.

## Commits
- **Conventional Commits** in English, imperative, title <= 72 chars: `feat(tools): add order lookup with identity check`.
- Types: `feat`, `fix`, `test`, `docs`, `refactor`, `chore`, `perf`.
- **Never** add `Co-Authored-By`, `Generated with Claude Code` or any AI attribution trailer.
- **Atomic, lean commits:** one logical change per commit, meaningful on its own, explainable by its title alone. Never mix concerns (feature + refactor + formatting + unrelated docs).
- Size guide: aim for <= ~300 changed lines of hand-written code per commit (data copies, lockfiles and generated files excluded). A bigger track is split into slices by behavior (e.g. catalog search, then product details), each with its own `test:` -> `feat:` pair.
- Generated or copied artifacts (challenge data, `uv.lock` with its dependency change, generated examples, eval reports) go in their own commits.
- Every non-`test:` commit leaves the suite green; `test:` commits are red by design (TDD).
- Never amend pushed commits, never force-push.
- Only the orchestrating agent runs `git`. Subagents never do.
