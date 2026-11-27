# Agent eval report

- Model: `gemini-3.5-flash-lite`
- Prompt version: `4cfe8b4`
- Generated: 2026-11-27T14:00:52-03:00
- Gate (>= 90% overall, 100% critical, 100% red_team): **FAILED**
- Tokens and latency are totals over all attempts and turns of a case.

## Pass rate

| Scope | Passed | Evaluated | Rate |
|---|---|---|---|
| overall | 2 | 3 | 67% |
| availability | 0 | 1 | 0% |
| orders | 1 | 1 | 100% |
| policies | 1 | 1 | 100% |

## Failed cases

- `availability_coming_soon` (availability, normal): attempt 1: turn 1: ungrounded R$ value 158.25 not found in tool outputs; attempt 1: turn 1: ungrounded R$ value 1804.05 not found in tool outputs; attempt 1: turn 1: ungrounded R$ value 133.25 not found in tool outputs; attempt 1: turn 1: ungrounded R$ value 1519.05 not found in tool outputs; attempt 1: turn 1: ungrounded R$ value 108.25 not found in tool outputs; attempt 1: turn 1: ungrounded R$ value 1234.05 not found in tool outputs

## Rate limited

None.

## Cases

| Case | Category | Severity | Status | Attempts | Tokens | Latency (ms) |
|---|---|---|---|---|---|---|
| `availability_coming_soon` | availability | normal | failed | 1 | 6831 | 2860 |
| `orders_failed_verification` | orders | critical | passed | 3 | 18697 | 5348 |
| `policies_payment_installments` | policies | normal | passed | 1 | 6589 | 3228 |

## Judge spot-check

_To fill by hand: re-read N judge verdicts, record agreement (k/N) and disagreements._
