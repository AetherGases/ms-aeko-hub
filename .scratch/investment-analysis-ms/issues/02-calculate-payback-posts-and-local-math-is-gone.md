# 02: `calculate_payback` posts to the calculator service and local investment math is gone

**GitHub:** https://github.com/AetherGases/ms-aeko-hub/issues/66

**What to build:** An agent calling `calculate_payback` still sends the same JSON as `calculate_roi` and still gets back `capex`, `wacc_monthly`, `months`, `vp_total`, `payback_months`, and `viable` (`payback_months` `-1` when the capex is not recovered). Behind that, this gateway POSTs to `{INVESTMENT_MS_BASE_URL}/calculator/payback` with the same auth, timeout, and error mapping as ROI. After this ticket there is no in-process present value, NPV, ROI percent, viability, or payback-month formula left in the gateway: a down calculator service cannot silently recalculate. Tool names, descriptions (including the 60-month horizon and `-1` sentinel), and catalog membership stay as they are.

**Blocked by:** 01: `calculate_roi` posts to the calculator service — https://github.com/AetherGases/ms-aeko-hub/issues/65

**Status:** blocked

**Triage:** blocked

**Owner:** this gateway

- [ ] `calculate_payback` POSTs snake_case JSON to `/calculator/payback` on the same `INVESTMENT_MS_BASE_URL`, `authentication-key`, and timeout as ROI
- [ ] A `200` JSON body is returned as-is (including the worked example → `payback_months` 2 when the service returns that payload)
- [ ] JSON string and dict inputs, local refusal of non-JSON, `validation_error` → `ValueError(message)`, and integration errors match the ROI client behaviour
- [ ] This gateway no longer computes present value, `vpl`, `roi_percent`, `viable`, or `payback_months`; those helpers and the tests that pinned them against in-process math are gone from here
- [ ] `calculate_roi` still uses the same client; both tools share one origin
- [ ] Tool name, description (`-1` and 60 months still advertised), ChatGPT anonymous catalog, and Coordenador de Melhoria Contínua kit membership are unchanged
- [ ] Success and refusal still log as `calculate_payback` succeeded / failed
- [ ] Tests go through the `calculate_payback` tool function with recorded HTTP; they do not re-implement payback arithmetic in the client
