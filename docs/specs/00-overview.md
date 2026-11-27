# Spec 00: Overview and contracts

## Goal
A customer service agent for Empório da Música that answers customers by text, decides when to query **data** (catalog, promotions, orders) and when to query **policies** (store manual), keeps the store persona and politely refuses out-of-scope requests.

## Architecture in one line
**Hybrid agent:** function calling over deterministic tools for operational data + **RAG** (lexical retrieval with BM25, section-level chunks) for the store manual. The model decides which source to query; the code guarantees prices, stock, orders and authorization.

## Stack (do not change without an ADR)
| Item | Choice |
|---|---|
| Agent | Google ADK (`google-adk`), single `Agent` with 5 tools, wrapped in an ADK `App` with 1 plugin |
| Model | `gemini-3.5-flash-lite` via Google AI Studio free tier (`GOOGLE_API_KEY`, project without billing); `MODEL` configurable |
| Guardrails | `SafetyPlugin` (ADK `BasePlugin`): local screening by default; Model Armor as an optional adapter (`MODEL_ARMOR_TEMPLATE`) |
| Loop / cost limit | ADK native `RunConfig(max_llm_calls=MAX_LLM_CALLS_PER_TURN)`; token usage read from `event.usage_metadata` |
| Sessions | ADK `DatabaseSessionService` on SQLite |
| Data | `pandas`, loaded once and cached |
| Policies (RAG) | `pypdf` extraction, section/subsection chunks, `rank-bm25`; embeddings evaluated as an experiment in phase 05 (ADR-003) |
| Fuzzy names | `rapidfuzz` |
| Interfaces | CLI (`rich`); `adk web` for a browser UI with traces, no custom code (ADR-004: no custom REST API) |
| Settings | `pydantic-settings` |
| Tests | `pytest` (deterministic) + agent evals (deterministic, grounding, LLM judge) + retrieval eval |

## Layout
```
data/                          # original challenge files (read-only)
src/musical_agent/
  config.py                    # Settings: MODEL, GOOGLE_API_KEY, AGENT_NOW, DATA_DIR, SESSION_DB_URL,
                               #           MODEL_ARMOR_TEMPLATE, MAX_LLM_CALLS_PER_TURN,
                               #           MAX_MESSAGE_CHARS, SUPPORT_DIR
  types.py                     # tool return contracts (TypedDict)
  data/loader.py               # CSV loading and normalization
  data/policies.py             # manual extraction, chunks, BM25 index
  domain/rules.py              # pure business rules (pricing, installments, withdrawal window, availability)
  tools/catalog.py             # search_products, get_product_details
  tools/orders.py              # get_order_status
  tools/policies.py            # search_policies
  tools/support.py             # register_complaint
  agent/prompt.py              # instruction builder
  agent/plugins/safety.py      # SafetyPlugin (local screening + optional Model Armor)
  agent/agent.py               # root_agent, app, respond()
  agent/__init__.py            # exports root_agent and app (so `adk web src` finds them)
  interfaces/cli.py
tests/  evals/  examples/  scripts/
docs/specs/  docs/decisions.md
```

## Tool contracts
```python
search_products(query: str = "", category: str = "", max_price: float | None = None,
                only_available: bool = True, limit: int = 8, tool_context=None) -> dict
# {"status": "ok", "products": [ProductSummary], "total": int} | {"status": "not_found"}

get_product_details(product: str, tool_context=None) -> dict
# id or name (fuzzy). {"status": "ok", "product": ProductDetail, "alternatives": [ProductSummary]}

get_order_status(order_number: int, email_or_phone: str, tool_context=None) -> dict
# {"status": "ok", "order": OrderDetail} | {"status": "verification_failed"} | {"status": "not_found"}

search_policies(question: str, k: int = 2) -> dict
# {"status": "ok", "passages": [{"section": str, "title": str, "text": str, "score": float}]}

register_complaint(summary: str, contact: str, order_number: int | None = None,
                   tool_context=None) -> dict
# {"status": "ok", "protocol": str, "response_deadline": "24 horas úteis"}
# | {"status": "invalid_contact"}
```
- `ProductSummary`: `id, name, category, original_price, final_price, discount_percent|None, promotion|None, stock, available`.
- `ProductDetail`: summary + `description, specs, catalog_status, pix_price|None, max_installments, installment_value`.
- `OrderDetail`: `number, date, status, status_label (pt-BR), items [{name, quantity}], total, payment_method, tracking_code|None, estimated_delivery|None, note|None, days_since_delivery|None, withdrawal_eligible|None, defect_exchange_eligible|None, legal_warranty_until|None, customer_first_name`.

## Business rules (source: manual + data)
1. Promotions: only `is_active == 1`; if several are active for a product, use the highest discount. Inactive promotions are ignored (e.g. product 95 has an inactive 12%).
2. Promotional prices are always shown with original price and % (manual 6.2).
3. PIX: 5% off list price; **not** cumulative with promotions (manual 6.2).
4. Installments (manual 3.1): up to 3x with min installment R$ 50; 4x-6x min R$ 80; 7x-12x min R$ 100. `max_installments` = largest n that satisfies the rule (1 if none).
5. Unavailable = stock 0, `discontinued` or `coming_soon`; return up to 3 alternatives in the same category, available, price within ±30% (closest price first).
6. Order lookup requires order number + customer email or phone (digits only). Only the customer's first name is returned. `total_brl` is the source of truth for totals.
7. After-sales windows, counted from the delivery date (`estimated_delivery` for `delivered` orders, assumption):
   - right of withdrawal (manual 4.1): 7 calendar days;
   - exchange for defect at the store (manual 4.2): 30 calendar days (the manual says "after purchase"; we count from delivery, assumption);
   - legal warranty (manual 8.1): 90 days.
   Orders not yet delivered return `None` for all windows (the window has not started).
8. All orders in `orders.csv` are treated as **online purchases** (they have shipping, tracking and delivery dates), so the right of withdrawal (4.1, "compras online") applies to them. For in-store purchases, the agent explains that 4.1 does not apply and points to the exchange for preference (4.3, 7 days).
9. Complaints (manual 7.3): listen with empathy, register with `register_complaint` (protocol + 24 business hours deadline). Requires a contact (email or phone). Stored in a local git-ignored file; contact is masked in logs.
10. Current date/time from `AGENT_NOW` (ISO) or system clock, timezone `America/Campo_Grande`.

## Definition of Done drives TDD
- Every phase spec ends with a **DoD table**: `| ID | Criterion | Verified by |`. The DoD is the acceptance spec; the track text only describes design.
- IDs: `PP.Tn` (phase, track, number), e.g. `02.C3`; phase-wide items use `PP.Xn`.
- `Verified by` is one of:
  - `test` -> at least one test marked `@pytest.mark.dod("02.C3")` (deterministic, no LLM) in `tests/`, or in `evals/` for model-dependent criteria;
  - `command` -> a command whose output is the evidence (e.g. `uv sync`);
  - `manual` -> only when automation makes no sense (e.g. "CI green on GitHub", "README read end to end"); evidence (link, transcript, screenshot path) goes in the phase summary.
- Prefer `test`. Use `manual` only with a reason.
- **TDD flow per track:** write the tests for the track's `test` rows first -> run them and see them fail for the right reason (red) -> implement until green -> refactor with tests green.
- `scripts/dod_check.py <ids>` (phase `02` or tracks `02.A 03.D`) fails if any `test` row in scope has no test with its marker; it runs in every wave verification and in CI (`--done`: every track marked `done`).

## Phases and execution
| Phase | Tracks |
|---|---|
| 01 Setup | single |
| 02 Data and rules | A: CSV loader · B: Manual index · C: Domain rules |
| 03 Tools | A: Catalog · B: Orders · C: Policies · D: Support |
| 04 Agent | A: Agent + prompt + state · B: Safety plugin · C: CLI |
| 05 Quality | A: Agent evals · B: Examples · C: CI gates · D: Retrieval eval |
| 06 README | single |

Tracks run across phases in **waves** (sequential) and **lanes** (parallel) according to their real dependencies: see `PLAN.md`.
