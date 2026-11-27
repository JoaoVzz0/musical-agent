# Spec 02: Data, manual index and domain rules

**Parallel tracks:** A, B, C (disjoint files).

## Track A: `data/loader.py` + `tests/test_loader.py`
- `load_dataset(data_dir) -> Dataset` (dataclass of DataFrames: products, categories, customers, orders, order_items, promotions), cached with `functools.lru_cache`.
- Normalize: `specs` JSON -> dict; prices as float; `name_normalized` (lowercase, no accents); phone digits only; dates as `date`; product with category name; order with item names.
- `active_promotion(dataset, product_id) -> Promotion | None` (rule 1).
- Tests: write the DoD rows `02.A*` first (TDD).

## Track B: `data/policies.py` + `tests/test_policies_index.py`
- Extract PDF text, strip headers/footers ("Página N", repeated title).
- Chunk by **numbered section** (1-10) and subsection (4.1, 4.2, ...) when present: `section`, `title`, `text`. Expose `chunks()` so the retrieval eval (phase 05) can reuse the same chunks for the embeddings experiment.
- `PolicyIndex.search(question, k)` with BM25; tokenization lowercase, accent-free, small pt-BR stopword list.
- Tests: write the DoD rows `02.B*` first (TDD).

## Track C: `domain/rules.py` + `tests/test_rules.py`
- Pure functions for rules 2-5 and 7: `final_price`, `pix_price`, `max_installments`, `is_available`, `pick_alternatives`, `after_sales_windows(delivery_date, today)` (withdrawal 7d, defect exchange 30d, legal warranty 90d).
- Business constants (5%, R$ 50/80/100, 7/30/90 days, ±30%) as named constants.
- Tests: write the DoD rows `02.C*` first (TDD).

## Assumptions to record in `docs/decisions.md`
- phone (67) 3341-4444 vs WhatsApp (67) 3321-4500;
- email with/without accent (`empóriodamusica` vs `emporiodamusica`);
- payment table ("parcela mínima R$ 100") vs installment rules 3.1 (3.1 wins: more specific);
- order totals that differ from item sums (orders 3 and 20: `total_brl` wins);
- delivery date = `estimated_delivery`; defect window counted from delivery;
- all orders in the data are online purchases (rule 8);
- no partner-store list exists for accessory redirects (manual 7.1): the agent says so instead of inventing one.

## DoD
| ID | Criterion | Verified by |
|---|---|---|
| 02.A1 | Counts: 65 products, 20 orders, 25 promotions, 50 customers | test |
| 02.A2 | Product 127 has active promotion 10% | test |
| 02.A3 | Product 95 has no active promotion (its 12% is inactive) and 96 has none | test |
| 02.A4 | With several active promotions for one product, the highest discount wins (synthetic frame) | test |
| 02.A5 | Phones normalized to digits; `specs` parsed to dict; `name_normalized` accent-free | test |
| 02.B1 | Chunks cover sections 1-10 and subsections (4.1-4.4, 5.1-5.3, ...); no "Página N" or repeated header in any chunk | test |
| 02.B2 | "me arrependi, posso devolver" -> 4.1 in top 2; "aceita pix" -> 3 in top 2; "horário sábado" -> 2 top 1; "frete para Dourados" -> 5.2 in top 2 | test |
| 02.C1 | `max_installments(429.90) == 5`; `max_installments(2199) == 12` with installment R$ 183,25 | test |
| 02.C2 | Installment boundaries per tier (R$ 50 / 80 / 100 minimums), including a value below R$ 50 -> 1x | test |
| 02.C3 | `pix_price(2199) == 2089.05`; `pix_price` is None when a promotion is active | test |
| 02.C4 | `final_price` applies the discount and rounds to cents | test |
| 02.C5 | `is_available` false for stock 0, `discontinued`, `coming_soon` | test |
| 02.C6 | `pick_alternatives`: same category, available, within ±30%, closest price first, max 3 | test |
| 02.C7 | `after_sales_windows`: withdrawal 7d, defect 30d, warranty 90d, each tested on the last valid day and the day after | test |
| 02.C8 | Not delivered -> all windows None | test |
| 02.X1 | Every item of "Assumptions to record" is in `docs/decisions.md` with the chosen interpretation | manual: prose, checked in review |
| 02.X2 | `uv run pytest tests/` green without network; `dod_check.py 02` passes | command |

## Commits
- A: `feat(data): load and normalize operational csv files`
- B: `feat(data): index store manual by section with bm25`
- C: `feat(domain): add pricing, installment and after-sales window rules`
- `docs: record data assumptions and manual inconsistencies`
