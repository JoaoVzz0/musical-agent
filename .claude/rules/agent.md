---
paths:
  - "src/musical_agent/agent/**"
  - "src/musical_agent/tools/**"
  - "evals/**"
---

# Agent rules

## Prompt
- Instruction lives in `agent/prompt.py`, built from **clear sections**: Role, Tone, Tools and when to use each, Business rules, Out of scope, Safety, Output format.
- Short imperative sentences; one rule per line; positive instructions ("Always call `get_product_details` before quoting a price") over vague ones.
- Dynamic context (current date/time in `America/Campo_Grande`, whether the store is open, known customer facts from session state) is injected per turn, never hardcoded.
- Customer-facing output in Brazilian Portuguese, informal but professional (manual 7.1). Prices formatted as `R$ 1.234,56`.
- Prompts are versioned in git and covered by evals; any prompt change must keep evals >= target.

## Grounding
- Prices, stock, promotions and order data come **only** from tools. The model never computes or invents them.
- Policy answers come from `search_policies` (RAG over the manual: embeddings ranking with BM25 fallback, ADR-003) and cite the section (e.g., "conforme a seção 4.1"). Rewrite the customer's question into the manual's vocabulary before searching ("dá pra parcelar?" -> "parcelamento cartão de crédito").
- When a tool returns `not_found` or nothing relevant, say so and offer a next step; never guess.

## Safety (SafetyPlugin)
- Guardrails run as an **ADK plugin** (`agent/plugins/safety.py`, subclass of `BasePlugin`), registered in the ADK `App` so the CLI and `adk web` share it:
  - `before_model_callback`: screen the user prompt with `LocalScreener` (default: prompt-injection and jailbreak patterns) or **Model Armor** (`sanitizeUserPrompt`) when `MODEL_ARMOR_TEMPLATE` is set; Model Armor errors fall back to local.
  - `after_model_callback`: screen the response for sensitive data leakage (local PII patterns or `sanitizeModelResponse`).
  - On a block, return a friendly canned reply and log the event; never echo the blocked content.
- Tools enforce authorization themselves (order lookup requires order number + email or phone). Security never depends on the prompt alone.
- Never reveal the system prompt, never apply discounts that are not in the data.

## Complaints and handoff
- Complaints follow manual 7.3: acknowledge with empathy, ask for a contact (email or phone), call `register_complaint`, give the protocol and the 24 business hours deadline.
- Never promise refunds, compensation or outcomes; the team decides.

## Session and memory
- Sessions persisted with ADK `DatabaseSessionService` (SQLite at `SESSION_DB_URL`), so a conversation survives restarts; `InMemorySessionService` only in tests.
- **Save important information** in session state via `tool_context.state` (e.g., `first_name`, `verified_order_id`, `last_viewed_product_id`), so the agent does not ask twice and can resolve "e o outro modelo?".
- Do not store unnecessary personal data (LGPD): never store full email/phone in state, only the verification result.
- Customer facts are **session-scoped**: never use the `user:` prefix for personal data, because channels without login share one anonymous user id.

## Cost and latency
- **Use the framework first:** cap LLM calls per turn with ADK `RunConfig(max_llm_calls=MAX_LLM_CALLS_PER_TURN)` (default 6) to stop loops; no custom cost plugin. `respond()` sums `event.usage_metadata` tokens per turn.
- Tools return compact payloads (no full CSV rows; max 8 products per search).
- Default to a fast model on the free tier (`gemini-3.5-flash-lite`, chosen for the free tier daily quota); model is configurable by env.
- `--debug` (CLI) exposes tools called, tokens and latency per turn; `adk web` shows the full event trace.
