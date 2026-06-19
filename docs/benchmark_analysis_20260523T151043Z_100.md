# pipi-eval-lab 100-Case Root Cause Analysis

Run ID: `20260523T151043Z`

Web report: `http://127.0.0.1:5173/`

JSON report: `reports/latest.json`

Suite: `benchmarks/food_beijing_onsite_100_v1.yaml`

## Corrected Result

The earlier 2% pass-rate reading was caused by an evaluator bug: `help_card_has_context` only accepted `context` as a string, while the backend correctly returns `context` as an object such as:

```json
{"city": "北京"}
```

After fixing the evaluator to accept any non-empty `context` value, the 100-case result is:

| Metric | Value |
| --- | --- |
| Backend | `http://67.230.169.161:8788` |
| Mode | `remote_smoke` |
| Health | passed |
| OpenAPI | passed |
| API contract | passed |
| Total | 100 |
| Passed | 52 |
| Degraded | 47 |
| Failed | 1 |
| Pass rate | 99.00% |
| Strict pass rate | 52.00% |
| Latency p50 | 510.738 ms |
| Latency p95 | 817.628 ms |

## Outcome Breakdown

| Expected -> Actual | Status | Count | Interpretation |
| --- | --- | ---: | --- |
| `show_help_card_draft -> show_help_card_draft` | passed | 50 | Unknown/insufficient-data cases correctly produced help cards. |
| `show_recommendation_card -> show_help_card_draft` | degraded | 47 | Recommendation was expected, but remote smoke has no broad seed coverage. Valid help-card fallback is acceptable in `remote_smoke`. |
| `show_recommendation_card -> show_recommendation_card` | passed | 2 | Seeded baseline recommendation cases passed. |
| `show_recommendation_card -> show_recommendation_card` | failed | 1 | Wrong recommendation type/location. |

## Real Failure

| Case | Expected | Actual |
| --- | --- | --- |
| `venue_order_031_haidilao_sanlitun` | `location_state=in_venue`, `target_type=ordering_bundle` | `location_state=in_area`, `target_type=restaurant` |

Input:

```text
我在三里屯海底捞，两个人不太能吃辣，帮我点
```

Actual card:

```text
三里屯川菜馆候选
```

Likely cause:

The backend matched the phrase `三里屯` to the seeded area recommendation path (`smoke.in_area`) before resolving the venue/order intent. It returned the seeded Sanlitun Sichuan restaurant recommendation instead of treating `三里屯海底捞` as a venue and producing an `ordering_bundle`.

## What This Means

The deployed backend is healthy and the API contract is present. The main service behavior is acceptable for remote smoke:

- 2 seeded recommendation paths pass strictly.
- 47 recommendation cases degrade safely to valid help cards because broad seed data is absent.
- 50 unknown/insufficient-data cases pass as help-card drafts.
- 1 venue-ordering case has a real intent/location routing bug.

## Recommended Next Fix

Prioritize the venue intent resolver:

1. If the input contains a known restaurant/chain/venue name plus ordering language such as `帮我点`, prefer `in_venue`.
2. Do not let area keywords like `三里屯` override venue names like `海底捞`.
3. Add a regression case for `我在三里屯海底捞，两个人不太能吃辣，帮我点`.
