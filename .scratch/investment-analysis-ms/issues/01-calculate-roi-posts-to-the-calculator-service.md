# 01: `calculate_roi` posts to the calculator service

**GitHub:** https://github.com/AetherGases/ms-aeko-hub/issues/65

**What to build:** An agent calling `calculate_roi` still sends the same JSON (string or object) and still gets back `capex`, `wacc_monthly`, `months`, `vp_total`, `vpl`, `roi_percent`, and `viable`. Behind that, this gateway POSTs the object to `{INVESTMENT_MS_BASE_URL}/calculator/roi` with the shared `authentication-key` and microservice timeout. A `validation_error` becomes the same kind of `ValueError` the agent already sees (the service `message`). A payload that is not a JSON object is refused locally, with no HTTP call. A down service, bad key (`unauthorized`), timeout, or 5xx is an integration failure, not bad agent JSON. `calculate_payback` may still compute locally in this ticket. The arithmetic `calculator` tool is unchanged.

**Blocked by:** None (can start immediately).

**Status:** todo

**Triage:** ready-for-agent

**Owner:** this gateway

- [ ] `calculate_roi` POSTs snake_case JSON to `/calculator/roi` on `INVESTMENT_MS_BASE_URL` with header `authentication-key` and the shared HTTP timeout
- [ ] A `200` JSON body is returned to the agent as-is (including the worked example `capex` 150 / `wacc_monthly` 0.25 / `cash_flows` `[125, 156.25]` → `vp_total` 200, `vpl` 50, `roi_percent` 33.33, `viable` true when the service returns that payload)
- [ ] JSON string and dict inputs produce the same POST body; unreadable non-JSON input never leaves the process and still raises the current “JSON object string” `ValueError`
- [ ] HTTP `validation_error` becomes `ValueError` whose text is the `message`; `unauthorized`, timeout, 5xx, and non-JSON bodies are integration errors
- [ ] Missing `INVESTMENT_MS_BASE_URL` or timeout setting fails by naming the setting
- [ ] Tool name, description, ChatGPT anonymous catalog membership, and which Aeko kit owns `calculate_roi` are unchanged
- [ ] Success and `validation_error` still log as `calculate_roi` succeeded / failed
- [ ] The arithmetic `calculator` tool still evaluates expressions in this gateway
- [ ] Tests go through the `calculate_roi` tool function with outbound HTTP recorded at the same requests boundary as Inventory/Cloudinary; they do not re-implement ROI arithmetic in the client
