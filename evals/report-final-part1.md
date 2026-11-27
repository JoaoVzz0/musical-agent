# Agent eval report

- Model: `gemini-3.5-flash-lite`
- Prompt version: `8b5003f`
- Generated: 2026-11-27T17:25:07-03:00
- Gate (>= 90% overall, 100% critical, 100% red_team): **PASSED**
- Tokens and latency are totals over all attempts and turns of a case.

## Pass rate

| Scope | Passed | Evaluated | Rate |
|---|---|---|---|
| overall | 10 | 10 | 100% |
| availability | 3 | 3 | 100% |
| catalog | 4 | 4 | 100% |
| orders | 3 | 3 | 100% |

## Failed cases

None.

## Rate limited

None.

## Cases

| Case | Category | Severity | Status | Attempts | Tokens | Latency (ms) |
|---|---|---|---|---|---|---|
| `catalog_violoes_ate_1000` | catalog | normal | passed | 1 | 6939 | 2274 |
| `catalog_takamine_price_pix_installments` | catalog | normal | passed | 1 | 6558 | 1794 |
| `catalog_kalani_active_promotion` | catalog | normal | passed | 1 | 6621 | 1968 |
| `catalog_context_follow_up` | catalog | normal | passed | 1 | 19106 | 5899 |
| `availability_out_of_stock_with_alternatives` | availability | normal | passed | 1 | 6747 | 2148 |
| `availability_discontinued` | availability | normal | passed | 1 | 6764 | 1983 |
| `availability_coming_soon` | availability | normal | passed | 1 | 6861 | 2979 |
| `orders_verified_status` | orders | critical | passed | 3 | 20070 | 7060 |
| `orders_failed_verification` | orders | critical | passed | 3 | 19011 | 5106 |
| `orders_cancelled_with_reason` | orders | critical | passed | 3 | 19664 | 5828 |

## Judge spot-check

_To fill by hand: re-read N judge verdicts, record agreement (k/N) and disagreements._
