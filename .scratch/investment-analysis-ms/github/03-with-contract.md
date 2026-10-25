## Parent

Parent issue of the calculator-service cutover for investment analysis (gateway repo): https://github.com/AetherGases/ms-aeko-hub/issues/64

## What to build

The calculator service accepts `POST /calculator/roi` and `POST /calculator/payback` with the shared `authentication-key`, validates the snake_case investment request, and returns the same JSON the tools already expose. Validation, 60-month padding, discounting `flow / (1 + wacc_monthly) ** m` for `m` in 1..60, two-decimal rounding, viability (`capex <= vp_total`), and payback month (first accumulated present value `>= capex`, else `-1`) live only here. Business refusals are `4xx` `{ "error_code": "validation_error", "message": "<current tool ValueError text>" }`. A missing or wrong key is `{ "error_code": "unauthorized", "message": "..." }`. This ticket can proceed in parallel with gateway ticket 01; gateway tests script HTTP and do not need a live service.

## Acceptance criteria

- [ ] `POST /calculator/roi` and `POST /calculator/payback` authenticate with `authentication-key` and speak snake_case JSON as in the parent contract
- [ ] Request rules match today’s tools: `capex` > 0, `0 <= wacc_monthly < 1`, exactly one of `cash_flows` (1..60 numbers) or `monthly_cash_flow`; unknown fields refused; booleans/non-numbers refused; messages match the current `ValueError` text
- [ ] Short `cash_flows` pad with zeros to 60 months; `monthly_cash_flow` repeats 60 times; month 1 is already discounted
- [ ] ROI `200` includes `months` 60, `vp_total`, `vpl`, `roi_percent` (two decimal places), `viable`; worked example `150` / `0.25` / `[125, 156.25]` → `vp_total` 200, `vpl` 50, `roi_percent` 33.33, `viable` true
- [ ] Payback `200` includes `payback_months` (2 on that example, `-1` when never recovered) and the same `viable` rule; a project can pay back and later be not viable
- [ ] `validation_error` vs `unauthorized` match the spec envelope; this service does not implement the arithmetic `calculator` tool

## Blocked by

None (can start immediately).

## HTTP Contracts

The gateway (`ms-aeko-hub`) POSTs an already-decoded JSON **object**. Empty string / invalid JSON is refused **before** this service is called.

This service currently uses JWT. The locked hub contract is the `authentication-key` header (Cloudinary-style), **not** a user Bearer.

### Routes

| Method | Path | Hub tool |
| --- | --- | --- |
| `POST` | `/calculator/roi` | `calculate_roi` |
| `POST` | `/calculator/payback` | `calculate_payback` |

- Origin: `INVESTMENT_MS_BASE_URL` (no `/v1`)
- `Content-Type: application/json`
- Header: `authentication-key: <INTERNAL_AUTHENTICATION_KEY>`
- Client timeout: `MS_HTTP_TIMEOUT`

### Request (same body on both routes)

Snake_case. Only these fields:

| Field | Type | Rule |
| --- | --- | --- |
| `capex` | number | `> 0`, finite, **not** boolean |
| `wacc_monthly` | number | `0 <= x < 1` (monthly decimal: `0.01` = 1% a month). An annual rate must be converted before it is sent |
| `cash_flows` **or** `monthly_cash_flow` | — | **exactly one** of the two |

- `cash_flows`: nonempty list, oldest first, 1..60 numbers (negative = a month that costs money). Missing months pad with `0` to length 60.
- `monthly_cash_flow`: one number (may be negative) **repeated 60 times**.

Unknown field → refusal. `true` / `false` is not a number.

```json
{ "capex": 150, "wacc_monthly": 0.25, "cash_flows": [125, 156.25] }
```

```json
{ "capex": 150000, "wacc_monthly": 0.01, "monthly_cash_flow": 5000 }
```

### Calculation (shared by both routes)

Constants: horizon **60**, unrecovered payback **-1**, rounding **2** decimal places.

1. **Build a 60-month series.** Short `cash_flows` concatenates zeros. `monthly_cash_flow` becomes 60 copies.

2. **Present value of each month** (`m` from **1 to 60**; month 1 is already discounted):

```
PV_m = flow_m / (1 + wacc_monthly) ** m
```

WACC 0 ⇒ `PV_m = flow_m`. A negative flow is discounted the same way.

3. **Totals from the raw (unrounded) sum**

- `vp_total_raw = sum(PV_m)`
- `vpl_raw = vp_total_raw - capex`
- `viable = capex <= vp_total_raw` (compare **without** rounding)
- `roi_percent_raw = vpl_raw / capex * 100`

4. **Payback.** Accumulate `PV_1 + PV_2 + …`. First month `m` whose accumulated value is `>= capex`. If none within 60 months → `-1`. A project can have a payback month and still be `viable: false` if later flows undo the recovery.

5. **Round only response money/percent fields** (Python 3 `round`, half-to-even, 2 places):

- `vp_total = round(vp_total_raw, 2)`
- `vpl` and `roi_percent` from the **raw** values, not from an already-rounded `vp_total`
- `capex` and `wacc_monthly` **echo the request** (do not round)
- `months` is always `60`

### Success `200`

`POST /calculator/roi`

```json
{
  "capex": 150,
  "wacc_monthly": 0.25,
  "months": 60,
  "vp_total": 200.0,
  "vpl": 50.0,
  "roi_percent": 33.33,
  "viable": true
}
```

`POST /calculator/payback` (same request)

```json
{
  "capex": 150,
  "wacc_monthly": 0.25,
  "months": 60,
  "vp_total": 200.0,
  "payback_months": 2,
  "viable": true
}
```

Worked example: `125 / 1.25 = 100`, `156.25 / 1.25² = 100` → VP 200, VPL 50, ROI `50/150*100 = 33.33`, payback in month 2.

| Request | Expected |
| --- | --- |
| capex 250, same flows | `vpl` -50, `roi_percent` -20, `viable` false, `payback_months` -1 |
| capex 100, wacc 0.25, `cash_flows: [125]` | `vp_total` 100, `roi_percent` 0, `viable` true, `payback_months` 1 |
| capex 250, wacc 0, `[100, 200, 300]` | `payback_months` 2, `vp_total` 600 |
| capex 290, wacc 0, `[100, 100, 100]` | `payback_months` 3 (accumulated, not the isolated month) |
| capex 5900, wacc 0, 30×200 + `[-6000]` + 29×200 | `payback_months` 30, `vp_total` 5800, `viable` false |
| capex 1000, wacc 0.01, `cash_flows: [333.333]` | `vp_total` 330.03, `vpl` -669.97 |

### Errors

Missing or wrong key — 4xx. The hub treats this as an **integration** failure, not bad agent JSON:

```json
{ "error_code": "unauthorized", "message": "..." }
```

Invalid request — 4xx. The hub raises `ValueError` with **only** `message` (English text of today’s tools):

```json
{ "error_code": "validation_error", "message": "<text below>" }
```

| Case | `message` (exact) |
| --- | --- |
| extra fields (`discount_rate`, `tax`) | `The request takes no discount_rate, tax. It accepts: capex, wacc_monthly, cash_flows, monthly_cash_flow.` (unknown fields **sorted**) |
| non-number / bool / inf / nan in `capex` | `"capex" must be a number, got {value!r}.` |
| `capex` ≤ 0 | `"capex" must be the initial investment, above zero, got {capex!r}.` |
| `wacc_monthly` not a number | `"wacc_monthly" must be a number, got {value!r}.` |
| wacc outside `[0, 1)` | `"wacc_monthly" must be the monthly discount rate as a decimal between 0 and 1 (0.01 is 1% a month), got {wacc!r}. An annual rate must be converted before it is sent.` |
| both flow fields, or neither | `The request must carry exactly one of "cash_flows" (the monthly flows, up to 60) or "monthly_cash_flow" (one flow repeated over the 60 months), got neither.` (or `cash_flows and monthly_cash_flow`) |
| `cash_flows` is not a nonempty list | `"cash_flows" must be a list of monthly cash flows, oldest first, got {flows!r}.` |
| more than 60 flows | `"cash_flows" must carry at most 60 monthly flows, one per month of the horizon, got {n}.` |
| invalid list item | `"cash_flows[{i}]" must be a number, got {value!r}.` |
| invalid `monthly_cash_flow` | `"monthly_cash_flow" must be a number, got {value!r}.` |

`{value!r}` is Python `repr` (`None`, `True`, `'150'`, `inf`, …).

### Out of scope for this service

The arithmetic `calculator` tool (AST expressions) stays in the hub. This service implements only ROI and payback. The hub will not recalculate locally if this service is down: timeout/5xx become an integration error there.
