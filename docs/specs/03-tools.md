# Spec 03: Agent tools

**Parallel tracks:** A, B, C, D. Each track edits only its tool module and its test file. Tools are thin adapters over `data` + `domain`.
Docstrings are read by the LLM: state when to use the tool, the arguments and what it returns.

## Track A: `tools/catalog.py` + `tests/test_catalog_tools.py`
- `search_products`, `get_product_details` per contract; fuzzy match (`rapidfuzz`) over name, category and description; category synonyms ("violao" -> Violões).
- Save `last_viewed_product_id` in `tool_context.state` when available.
- Tests: write the DoD rows `03.A*` first (TDD).

## Track B: `tools/orders.py` + `tests/test_order_tools.py`
- `get_order_status` with verification (rule 6) and after-sales windows (rules 7, 8, 10).
- `status_label`: delivered "entregue", shipped "a caminho", confirmed "confirmado, em separação", pending "aguardando pagamento", cancelled "cancelado".
- Return only the customer's first name. On success save `verified_order_id` and `first_name` in **session-scoped** state (no `user:` prefix: the CLI and `adk web` share one anonymous user id, so user-scoped keys would leak a verified name into other conversations); never store email/phone.
- Tests: write the DoD rows `03.B*` first (TDD).

## Track C: `tools/policies.py` + `tests/test_policy_tool.py`
- `search_policies` returns passages with section and title for citation.
- Ranking (ADR-003, decided by the retrieval eval): embeddings (`gemini-embedding-001`, cosine) over the same section chunks; chunk embeddings computed once and cached on disk (`var/`, keyed by model + chunks hash); BM25 (`PolicyIndex.search`) is the fallback when no API key is configured or the embeddings call fails, so the tool never breaks.
- Tests: write the DoD rows `03.C*` first (TDD).

## Track D: `tools/support.py` + `tests/test_support_tool.py`
- `register_complaint` (rule 9): validates contact (email or phone with 10-11 digits), creates protocol `RC-YYYYMMDD-NNNN`, appends a JSON line to `SUPPORT_DIR/complaints.jsonl` (git-ignored `var/`), returns protocol and "24 horas úteis".
- Docstring: use only after listening to the complaint and having a contact; never for simple questions.
- Tests: write the DoD rows `03.D*` first (TDD).

## DoD
| ID | Criterion | Verified by |
|---|---|---|
| 03.A1 | Violões <= R$ 1000 available exclude ids 96 and 113 | test |
| 03.A2 | "takamine gd20" resolves id 95: R$ 2.199,00, no promotion, PIX R$ 2.089,05, 12x | test |
| 03.A3 | Product 127 returns original price, final price and 10% | test |
| 03.A4 | Product 96 returns `available=False` and up to 3 alternatives | test |
| 03.A5 | Category synonyms ("violao", "guitarra") and typos resolve | test |
| 03.A6 | Search returns at most 8 compact items (no description/specs) | test |
| 03.A7 | `last_viewed_product_id` saved in `tool_context.state` | test |
| 03.B1 | Order 1 + `pedro.oliveira@jmail.com` -> ok with first name only; payload has no email, phone or address | test |
| 03.B2 | Wrong email -> `verification_failed`; masked phone `(67) 98432-1098` matches | test |
| 03.B3 | Order 99 -> `verification_failed`, the same answer as a wrong e-mail (an attacker cannot learn which order numbers exist); cancelled order includes `note` | test |
| 03.B4 | Order 7 at 2026-02-20 -> `withdrawal_eligible` True | test |
| 03.B5 | Order 7 at 2026-03-25 -> withdrawal False, defect exchange False, legal warranty valid | test |
| 03.B6 | Shipped order 8 -> all windows None | test |
| 03.B7 | State stores `verified_order_id` and session-scoped `first_name`, never email or phone, and no `user:`-scoped key | test |
| 03.C1 | `search_policies` returns passages with `section`, `title`, `text`, `score`; top-1 correct for 3 questions | test |
| 03.C2 | With embeddings available, ranking comes from embeddings; without a key or when the embeddings call fails, BM25 answers (fake embedder) | test |
| 03.C3 | Chunk embeddings are cached on disk keyed by model and chunks; a second load makes no document-embedding calls | test |
| 03.D1 | Valid contact -> protocol `RC-YYYYMMDD-NNNN`, one JSON line written | test |
| 03.D2 | Invalid contact -> `invalid_contact`, nothing written | test |
| 03.D3 | Logs never contain the full contact (caplog) | test |
| 03.X1 | Every tool returns a JSON-serializable dict with `status` and never raises, for invalid inputs and a broken data dir (`tests/test_tool_contracts.py`, written in integration) | test |
| 03.X2 | Rules 1-10 each covered by at least one DoD test across phases 02-03 (mapping in the phase summary) | manual: traceability review |

## Commits
- A: `feat(tools): add product search and details with promotions`
- B: `feat(tools): add order lookup with identity verification`
- C: `feat(tools): add store policy search`
- D: `feat(tools): add complaint registration with protocol`
