# 03: Calculator service implements ROI and payback

**GitHub:** https://github.com/AetherGases/aether-ms-calculator/issues/3

**What to build:** The calculator service (not this gateway) accepts `POST /calculator/roi` and `POST /calculator/payback` with the shared `authentication-key`, validates the snake_case investment request, and returns the same JSON the tools already expose. Validation, 60-month padding, discounting `flow / (1 + wacc_monthly) ** m` for `m` in 1..60, two-decimal rounding, viability (`capex <= vp_total`), and payback month (first accumulated present value `>= capex`, else `-1`) live only here. Business refusals are `4xx` `{ "error_code": "validation_error", "message": "<current tool ValueError text>" }`. A missing or wrong key is `{ "error_code": "unauthorized", "message": "..." }`. This ticket can proceed in parallel with 01; the gateway tests script HTTP and do not need a live service.

**Blocked by:** None (can start immediately).

**Status:** todo

**Triage:** ready-for-agent (calculator service team; not this gateway)

**Owner:** calculator service team

- [ ] `POST /calculator/roi` and `POST /calculator/payback` authenticate with `authentication-key` and speak snake_case JSON as in the spec
- [ ] Request rules match today’s tools: `capex` > 0, `0 <= wacc_monthly < 1`, exactly one of `cash_flows` (1..60 numbers) or `monthly_cash_flow`; unknown fields refused; booleans/non-numbers refused; messages match the current `ValueError` text
- [ ] Short `cash_flows` pad with zeros to 60 months; `monthly_cash_flow` repeats 60 times; month 1 is already discounted
- [ ] ROI `200` includes `months` 60, `vp_total`, `vpl`, `roi_percent` (two decimal places), `viable`; worked example `150` / `0.25` / `[125, 156.25]` → `vp_total` 200, `vpl` 50, `roi_percent` 33.33, `viable` true
- [ ] Payback `200` includes `payback_months` (2 on that example, `-1` when never recovered) and the same `viable` rule; a project can pay back and later be not viable
- [ ] `validation_error` vs `unauthorized` match the spec envelope; this service does not implement the arithmetic `calculator` tool
