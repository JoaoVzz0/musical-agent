---
name: implement-wave
description: Implements one wave of the Empório da Música agent from docs/specs/PLAN.md, running the wave's lanes in parallel with subagents (DoD-driven TDD), validating every DoD row, committing with Conventional Commits without AI attribution and, with --auto, pushing. Use when the user asks to "implement wave N" or runs /implement-wave N.
---

# Implement wave

Argument: wave number (`0`-`5`, see `docs/specs/PLAN.md`) or `all`. Optional `--auto` for autonomous runs: commit without asking for approval and push at the end of the wave (authorized by the user).

`all`: run every wave not yet `done`, in order (W0 -> W5), each one going through steps 1-6 completely (verified, committed, pushed with `--auto`, CI checked) before the next starts. Between waves, print a one-paragraph progress note (wave done, DoD summary, commits, CI result). Stop and report only on a blocker:
- missing prerequisite (`challenge/`, git remote, `.env` before W3) -> finish the offline work possible and stop;
- a DoD row that cannot pass without changing the spec or a test expectation;
- CI still red after 2 fix attempts, or repeated 429 after backoff;
- deadline passed.
The final README read (W5 checkpoint) is reported as a to-do for the user, not a blocker.

## 1. Prepare
1. Read `CLAUDE.md`, every file in `.claude/rules/`, `docs/specs/00-overview.md`, `docs/specs/PLAN.md`, `docs/specs/STATUS.md` and the phase specs of every track in the wave.
2. Stop if any track the wave depends on (PLAN.md "Track dependencies") is not `done`, or if `git status` is not clean. Exception for W0: the kit files (`CLAUDE.md`, `.gitignore`, `.claude/`, `docs/`) are expected to be untracked and are committed by W0 (`HOW_TO_USE.md` is git-ignored); `challenge/` must exist with the challenge files.
3. For each lane: tracks (in order), exact files owned, DoD rows. Lanes must not share files; shared files (`pyproject.toml`, `types.py`, `config.py`, `conftest.py`, `docs/decisions.md`, `STATUS.md`) belong to the orchestrator.
4. Waves with an API lane (W3, W4) need `.env` with `GOOGLE_API_KEY`; check that the file exists (never read or print it). If missing, run the offline lanes and stop before the API lane.

## 2. Run lanes in parallel
- Launch **one subagent (Agent tool) per lane in the same message** so they run concurrently. Single-lane waves: implement directly, no subagent.
- Each subagent prompt must include:
  - the track sections and **their DoD rows** copied from the specs, the contracts and business rules from spec 00, and the rule files that apply to its paths;
  - the exact list of files it may create or edit, and nothing else;
  - "TDD: first write one or more tests per `test` DoD row, each marked `@pytest.mark.dod(\"<ID>\")`; run them and confirm they fail for the right reason (red); then write the code until green; then refactor with tests green. Run `uv run pytest <your tests>` and `uv run ruff check <your files>`";
  - "never write `#` comments (no inline, no above-line, no commented-out code); functions must be self-explanatory; docstrings (Google style) only on agent tools and complex or non-obvious public functions";
  - "do not run git, do not call the real model, do not edit files outside your list, do not change `types.py` or other shared files; if the contract does not fit, stop and report";
  - "reply with: files changed, DoD ID -> test name mapping, red run output (short), green run output, assumptions made".
- A lane that depends on an interface not built yet (e.g. CLI on `respond()`) works on a stub of the agreed signature; the orchestrator integrates it in the wave that builds the real one.

## 3. API lane (orchestrator only, sequential)
- Run the API steps of the wave in the order given in PLAN.md, one at a time. On 429, back off and retry; never run API steps in parallel.
- Real eval failures are fixed in the agent (prompt, tools), committed as `fix(agent): ...`, and the eval is re-run. Never edit a case to make it pass.

## 4. Integrate and verify
1. Read every subagent report and review the diffs (`git diff`).
2. Write the wave's integration rows (`PP.X*`), test-first.
3. Run the full gates: `uv run pytest tests/`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run python scripts/dod_check.py <track ids of the wave>`, `uv run python scripts/check_comments.py`. Fix integration issues.
4. Check the code against the rules (SRP, no `#` comments, docstrings only where required, typing, no magic numbers, grounding, safety plugin, `RunConfig` limit, state, security layers).
5. If the wave touched the prompt, tools or plugins and evals exist, run `uv run pytest -m evals` and enforce the gates from `.claude/rules/security.md`. If it touched `data/policies.py`, also run the retrieval eval.
6. Report the DoD table with evidence per row: `test` -> test name(s) passing; `command` -> command + result; `manual` -> link/transcript. No evidence = not done. A `test` row is never downgraded to `manual` to make a wave pass.
7. Record new assumptions in `docs/decisions.md`.

## 5. Human review
- Without `--auto`: show a short summary (what each lane did, DoD with evidence, planned commits) and **wait for approval** before committing.

## 6. Commit and push
- Per track, in the order of the wave table: first `test(<scope>): ...` with the tests only (they fail at that commit, which documents TDD in the history), then the spec's `feat`/`fix` commit with the code. Stage only that track's files (`git add <files>` or `git add -p` for slices), never a blind `git add -A`.
- **Atomic and lean** (see `CLAUDE.md`): the spec's commit list is the minimum, not the maximum. Before committing, check `git diff --stat`; if a track exceeds ~300 hand-written lines or mixes concerns, split it into behavior slices, each a `test:` -> `feat:` pair with a specific title (e.g. `feat(tools): add product search with category synonyms`, then `feat(tools): add product details with pix and installments`). Integration fixes, refactors and doc updates are separate commits. Each non-`test:` commit must leave `uv run pytest tests/` green (verify while building the sequence).
- Use the Conventional Commit messages from the specs (English, imperative, title <= 72 chars); when a track is split, the last slice keeps the spec title or each slice gets a more specific title in the same scope.
- **Never** add `Co-Authored-By`, `Generated with Claude Code` or any AI trailer. Use `git commit -m "<title>"` (plus `-m "<body>"` if needed).
- Update `docs/specs/STATUS.md` (tracks `done` + short hashes) in `docs: update status for wave N`.
- Without `--auto`: do not push; tell the user the wave is ready for `git push`.
- With `--auto`: only after every DoD row of the wave has evidence, run `git push origin main` (plain push; never `--force`, never amend pushed commits). Then check CI through the public GitHub API (`curl -s https://api.github.com/repos/<owner>/<repo>/actions/runs?branch=main&per_page=1`, owner/repo from `git remote get-url origin`), polling until the run completes (from W1 on, when CI exists). If CI fails, fix with a new `fix:` commit and push again.
- Stop and report instead of pushing if the deadline has passed or `git status` shows files outside the wave.

## Guardrails
- No scope creep: good ideas outside the spec go to the README "Next steps".
- Prices, stock, promotions and orders always come from deterministic code.
- Date-dependent tests always fix `AGENT_NOW`.
- Never edit a DoD row or a test expectation to make it pass; if the spec is wrong, stop and ask, then record the change in `docs/decisions.md`.
