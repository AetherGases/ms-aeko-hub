## What to build

Move `calculate_roi` and `calculate_payback` off this gateway onto the calculator service. Agents keep the same tool names, JSON, and refusals. The arithmetic `calculator` tool stays local.

This issue is the parent. Each ticket below is a sub-issue.

## HTTP contract (calculator service)

- Origin: `INVESTMENT_MS_BASE_URL`
- `POST /calculator/roi` and `POST /calculator/payback`
- Header `authentication-key` = `INTERNAL_AUTHENTICATION_KEY`
- Timeout: `MS_HTTP_TIMEOUT`
- Snake_case JSON: `capex`, `wacc_monthly`, and exactly one of `cash_flows` | `monthly_cash_flow`
- `200` ROI: `capex`, `wacc_monthly`, `months`, `vp_total`, `vpl`, `roi_percent`, `viable`
- `200` payback: `capex`, `wacc_monthly`, `months`, `vp_total`, `payback_months`, `viable`
- Business refusal: `{ "error_code": "validation_error", "message": "<current tool ValueError text>" }`
- Bad key: `{ "error_code": "unauthorized", "message": "..." }`
- Worked example: `{ "capex": 150, "wacc_monthly": 0.25, "cash_flows": [125, 156.25] }` → `vp_total` 200, `vpl` 50, `roi_percent` 33.33, `viable` true, `payback_months` 2

Gateway mapping: `validation_error` → `ValueError(message)`. Timeout, `unauthorized`, 5xx, non-JSON → integration error. No local fallback.

## Tickets

- **01** (this gateway): https://github.com/AetherGases/ms-aeko-hub/issues/65
- **02** (this gateway, blocked by 01): https://github.com/AetherGases/ms-aeko-hub/issues/66
- **03** (calculator service team, parallel): https://github.com/AetherGases/aether-ms-calculator/issues/3

## Out of scope

Implementing the arithmetic `calculator` tool on the service. Changing ChatGPT/Aeko tool names or catalog membership. A committed OpenAPI file in this git tree.

## Notes

Local spec and ticket copies live under `.scratch/investment-analysis-ms/` and are not committed.
