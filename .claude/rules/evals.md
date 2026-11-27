---
paths:
  - "evals/**"
  - "scripts/generate_examples.py"
  - "src/musical_agent/data/policies.py"
  - "src/musical_agent/agent/prompt.py"
---

# Eval rules

## What an eval case is
- One case = one customer intent, written as real customer messages in pt-BR (typos and informal language included).
- Each case declares: `id`, `category`, `agent_now` (ISO, data spans 2025-10 to 2026-03), `turns`, `expected_tools` (ordered or set), `must_contain`, `must_not_contain`, `criteria` (judge rubric), `severity` (`critical` | `normal`).
- A case that verifies a manual DoD row of an earlier phase lists it in `dod: ["04.M1"]`, so the manual check becomes an automated regression.
- Cases come from the spec scenarios, the manual's special situations (7.3) and real failures found while testing. Every bug fixed becomes a new case (regression).

## Coverage (minimum per category)
| Category | Min cases |
|---|---|
| catalog search / price / promotion | 4 |
| unavailable, discontinued, coming soon | 2 |
| orders (verified, failed verification, cancelled) | 3 |
| policies (withdrawal in/out of window, payment, shipping, hours, store closed) | 5 |
| complaint registration | 1 |
| out of scope (accessories, unrelated topics) | 2 |
| red team (injection, fake discount, prompt leak, PII fishing) | 4 |

## Three layers of checks, cheapest first
1. **Deterministic:** expected tools were called with valid arguments; `must_contain` / `must_not_contain` (e.g. exact price string, no price for an unavailable product).
2. **Grounding:** every price, stock value or order status in the reply matches the tool output of that turn (parse `R$` values and compare).
3. **LLM judge:** only for tone, helpfulness and policy correctness. Judge uses a different, fixed prompt; returns JSON `{"passed": bool, "reason": str}`; temperature 0.

## Judge rules
- Rubric is specific and binary ("cites section 4.1 and says the 7-day window counts from delivery"), never "is the answer good?".
- Judge sees the conversation, the tool outputs and the rubric; never the agent's system prompt.
- Spot-check judge verdicts by hand on the first run and record agreement in the report.

## Running and reporting
- `uv run pytest -m evals` runs against the real model with the case's `agent_now` and a fresh in-memory session per case.
- Report `evals/report.md`: pass rate overall and per category, failed cases with reason, tokens and latency per case, model and prompt version (git short hash).
- Run policy (Gemini free tier, keep requests low): every case runs **once**; `critical` cases run **3 times** and pass only with 3/3. Add a short delay between cases and retry on 429 with backoff; a 429 is reported as `rate_limited`, never as a failure.
- Never edit a case to make it pass; fix the agent or document why the expectation was wrong in `docs/decisions.md`.

## Retrieval eval (policy RAG)
- `evals/retrieval_cases.yaml`: raw customer questions in pt-BR labeled with the expected section(s); cover every manual section that customers ask about (2-8) and paraphrases without the manual's words ("dá pra parcelar?", "demora quanto pra chegar em Dourados?").
- Metrics: recall@2 and MRR for BM25, embeddings and hybrid (RRF) over the **same chunks**.
- BM25 gate runs offline in `pytest tests/`-compatible form (recall@2 >= 90%); embeddings use `gemini-embedding-001` with a disk cache and are marked `evals`.
- The strategy changes only if the decision rule in spec 05 triggers; the result is recorded in ADR-003 and the README.
