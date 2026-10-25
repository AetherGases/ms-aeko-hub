# Calculator service for investment analysis

Status: ready-for-agent

Tracker: this file under `.scratch/investment-analysis-ms/`. Tickets belong beside it and as cards on [AetherGases Project 1, view 11](https://github.com/orgs/AetherGases/projects/1/views/11). Do not add a contract file to git.

## Problem Statement

Aeko and ChatGPT already call `calculate_roi` and `calculate_payback` as if investment math lived in this gateway. That math now belongs in another internal service, but the people and agents using the tools must not notice: same names, same JSON, same refusals. The arithmetic `calculator` tool is a different thing and must stay here.

## Solution

This gateway keeps the two investment tools and turns them into a thin client of the calculator service. The service owns validation and the discounted-cash-flow arithmetic. Agents still speak to `calculate_roi` and `calculate_payback`. A missing service is a failed tool call, not a silent local recalculation.

## User Stories

1. As an Aeko analyst agent, I want `calculate_roi` to keep accepting the JSON I already send, so that existing prompts and tool calls keep working.
2. As an Aeko analyst agent, I want `calculate_payback` to keep accepting the same JSON as `calculate_roi`, so that I can ask “is it worth it?” and “how long until it pays back?” as two questions.
3. As an Aeko analyst agent, I want the ROI answer to still carry `capex`, `wacc_monthly`, `months`, `vp_total`, `vpl`, `roi_percent`, and `viable`, so that I can rank proposals without learning a new shape.
4. As an Aeko analyst agent, I want the payback answer to still carry `capex`, `wacc_monthly`, `months`, `vp_total`, `payback_months`, and `viable`, so that I can say how long the company waits.
5. As an Aeko analyst agent, I want `payback_months` to be `-1` when the capex is not recovered inside the horizon, so that I do not invent a month that never comes.
6. As an Aeko analyst agent, I want a project that exactly covers its capex in present value to be `viable: true` with `roi_percent` 0, so that “pays for itself” is not stricter than the current rule.
7. As an Aeko analyst agent, I want to send either `cash_flows` (oldest month first, missing months counting as zero) or `monthly_cash_flow` (one net flow repeated), so that I can describe both lumpy and flat projects.
8. As an Aeko analyst agent, I want a month that costs money to stay a negative flow, so that opex during the project is not silently dropped.
9. As an Aeko analyst agent, I want a refusal to name the field I got wrong in the same wording as today, so that I can correct the JSON without a new error dialect.
10. As an Aeko analyst agent, I want an empty, non-JSON, or non-object payload refused before any HTTP call, so that I am told I did not send a JSON object string.
11. As an Aeko analyst agent, I want `"{}"` and other well-formed but incomplete objects refused with the same field messages as today, so that missing `capex` still reads as a `capex` problem.
12. As an Aeko analyst agent, I want unknown fields refused and the allowed fields listed, so that I do not send annual WACC under a new name and think it was used.
13. As an Aeko analyst agent, I want booleans, infinities, and non-numbers rejected as “must be a number”, so that `true` is not treated as `1`.
14. As an Aeko analyst agent, I want `capex` at or below zero refused, so that I cannot discount a project that has no investment.
15. As an Aeko analyst agent, I want `wacc_monthly` outside `0 <= wacc < 1` refused, with the reminder that an annual rate must be converted first, so that I do not send 12% as `12`.
16. As an Aeko analyst agent, I want sending both `cash_flows` and `monthly_cash_flow`, or neither, refused, so that the service never guesses which series to use.
17. As an Aeko analyst agent, I want more than 60 monthly flows refused, so that a longer list cannot quietly change the horizon.
18. As an Aeko analyst agent, I want the arithmetic `calculator` tool to keep evaluating expressions in this gateway, so that `2 + 2` does not depend on the calculator service.
19. As a ChatGPT Apps user, I want `calculate_roi` and `calculate_payback` to remain anonymous tools, so that Sign in is not required to run investment math.
20. As a ChatGPT Apps user, I want `calculator` to remain an anonymous local tool, so that arithmetic and investment stay two different calls.
21. As the Coordenador de Melhoria Contínua agent, I want to keep both investment tools in my kit, so that I can judge improvement proposals.
22. As any other Aeko agent, I want not to gain or lose investment tools in this change, so that only the backing of ROI/payback moves.
23. As the gateway process, I want to POST the parsed JSON object to `/calculator/roi` or `/calculator/payback` on the calculator service, so that I do not reimplement present value, NPV, ROI percent, or payback month.
24. As the gateway process, I want to send the shared internal `authentication-key`, so that the calculator service can reject callers that are not us.
25. As the gateway process, I want to wait only as long as the shared microservice HTTP timeout, so that a hung calculator service cannot stall an agent turn forever.
26. As the gateway process, I want a `validation_error` body to become the same `ValueError` the tools raise today, using the service `message`, so that agents and logs keep seeing a refused request rather than an HTTP status.
27. As the gateway process, I want a missing or wrong internal key (`unauthorized`), a timeout, a 5xx, or a non-JSON body to fail as an integration error, so that a broken service is not reported as bad agent JSON.
28. As the gateway process, I want no local copy of the investment formulas after cutover, so that a down calculator service cannot silently disagree with a future service change.
29. As the gateway process, I want a JSON object the agent already parsed as a dict to POST as that object, so that LangChain dict calls and JSON-string calls hit the same endpoint.
30. As an operator, I want a single `INVESTMENT_MS_BASE_URL` for both ROI and payback, so that I do not configure two hosts for one service.
31. As an operator, I want to reuse the existing internal authentication key and HTTP timeout, so that the calculator service joins Cloudinary-style internal calls rather than inventing new secrets.
32. As an operator, I want a missing base URL or timeout to fail by naming the setting, so that local startup errors are configuration errors, not tool-input errors.
33. As the team that implements the calculator service, I want the HTTP contract written in this spec, so that I can implement `/calculator/roi` and `/calculator/payback` without cloning a YAML out of this git tree.
34. As the team that implements the calculator service, I want validation and arithmetic to live only with me, so that the gateway cannot drift from the horizon, rounding, or refusal text.
35. As the team that implements the calculator service, I want a short `cash_flows` list padded with zeros out to 60 months, and `monthly_cash_flow` repeated 60 times, so that discounting always runs over the fixed horizon.
36. As the team that implements the calculator service, I want each month `m` (1..60) discounted as `flow / (1 + wacc_monthly) ** m`, so that month 1 is already discounted and a zero WACC leaves flows unchanged.
37. As the team that implements the calculator service, I want money fields rounded to two decimal places in the response, so that `vp_total`, `vpl`, and `roi_percent` match what agents already print.
38. As the team that implements the calculator service, I want `payback_months` to be the first month whose accumulated present value is at least `capex`, even if later months make the project not viable, so that “when it first pays back” is not the same question as “whether it stays worth it”.
39. As a developer of this gateway, I want tool names, descriptions, and ChatGPT catalog membership unchanged, so that MCP allowlists and agent kits do not churn.
40. As a developer of this gateway, I want tool descriptions to keep advertising the 60-month horizon and `-1` payback sentinel, so that agents still write legal JSON even though those numbers are enforced by the service.
41. As a developer of this gateway, I want observability to keep logging `calculate_roi` / `calculate_payback` success and failure, so that a refused request and a down service still show up as tool lines.
42. As a future reader of this spec, I want “calculator service” to mean the HTTP service at `/calculator/*`, and “calculator tool” to mean the local arithmetic tool, so that the shared path prefix is not mistaken for moving AST evaluation.

## Implementation Decisions

- This change is a client cutover in the gateway, not a new agent-facing tool and not a rewrite of the arithmetic calculator tool.
- One outbound integration client talks to the calculator service, in the same style as the Cloudinary client (internal authentication key, shared HTTP timeout, JSON in and out) rather than the Inventory client (user Bearer).
- The finance tools module stops computing present value, NPV, ROI percent, viability, and payback month. It keeps registering `calculate_roi` and `calculate_payback` with the same names and descriptions, decodes the agent payload into a JSON object when the agent sent a string, and delegates to the client.
- Decoding a string into a JSON object is transport. Field validation, horizon padding, and arithmetic are the calculator service’s.
- Environment: `INVESTMENT_MS_BASE_URL` is the service origin with no trailing slash required of callers; paths are appended. Timeout is the existing shared microservice timeout. The header name is `authentication-key`; the value is the existing internal authentication key. There is no API version segment.
- HTTP contract (calculator service):

  - `POST {INVESTMENT_MS_BASE_URL}/calculator/roi`
  - `POST {INVESTMENT_MS_BASE_URL}/calculator/payback`
  - `Content-Type: application/json`
  - Request object, snake_case, only these properties: `capex` (number > 0), `wacc_monthly` (number, `0 <= wacc_monthly < 1`), and exactly one of `cash_flows` (non-empty array of numbers, length 1..60, oldest first) or `monthly_cash_flow` (number, including negative). Unknown properties are rejected.

  - Success `200` for ROI:

    ```
    {
      capex, wacc_monthly, months, vp_total, vpl, roi_percent, viable
    }
    ```

    `months` is 60. `vp_total` is the sum of discounted flows. `vpl` is `vp_total - capex`. `roi_percent` is `vpl / capex * 100`. `viable` is true iff `capex <= vp_total`. Money and percentage fields are rounded to two decimal places. `capex` and `wacc_monthly` echo the request.

  - Success `200` for payback:

    ```
    {
      capex, wacc_monthly, months, vp_total, payback_months, viable
    }
    ```

    `payback_months` is the first month in 1..60 whose accumulated present value is `>= capex`, or `-1` if none. `viable` uses the same rule as ROI. A project can have a payback month and still be not viable if later flows undo the recovery.

  - Discounting: for month `m` from 1 to 60, present value is `flow_m / (1 + wacc_monthly) ** m`. Short `cash_flows` lists are padded with `0` to 60 months. `monthly_cash_flow` becomes 60 copies of that number.

  - Business refusal: `4xx` with `{ "error_code": "validation_error", "message": "<current tool ValueError text>" }`. The message is the contract the agent already depends on (it names the bad field, the 60-month horizon, and the WACC range including “0.01 is 1% a month”).

  - Bad or missing internal key: `{ "error_code": "unauthorized", "message": "..." }` with a 4xx status. The gateway treats this as an integration failure, not a tool-input `ValueError`.

- Gateway mapping: HTTP `200` object is returned as the tool result as-is. `validation_error` becomes `ValueError` whose string is the `message`. Timeout, connection failure, `unauthorized`, status `>= 500`, and a success or error body that is not a JSON object become the client’s integration error (same role as Cloudinary/Inventory transport errors).
- No local fallback and no dual implementation: once the tools call the service, the old in-process formulas are gone from this gateway.
- Agent-facing freeze: ChatGPT anonymous catalog still includes `calculator`, `calculate_roi`, and `calculate_payback`. Only the Coordenador de Melhoria Contínua Aeko kit exposes the two investment tools, plus the arithmetic calculator it already had. Descriptions stay in this process’s environment and must keep describing the 60-month horizon and `-1` sentinel so they do not drift from the service.
- Naming: “calculator service” is the HTTP service (`/calculator/roi`, `/calculator/payback`). “calculator tool” is the local AST arithmetic tool. They share a word on purpose; they do not share an implementation.
- This spec is the shared contract. Do not add an OpenAPI file to the git working tree. Do not put `.scratch/` on git.

## Testing Decisions

- Test external behaviour of the two investment tools: what the agent can send, what JSON comes back, which exception type and message the agent sees, which HTTP method/url/headers/body left the process, and that the arithmetic calculator tool is untouched.
- Do not test in-process present-value helpers, horizon padding, or field-by-field parsers in this gateway after cutover. Those behaviours are the calculator service’s. Tests that currently pin that math against private functions should be retired here (they belong with the service) rather than rewritten to re-implement the formulas in the client.
- Single seam: the public `calculate_roi` and `calculate_payback` tool functions. Record outbound HTTP at the same `requests.request` boundary already used for Inventory and Cloudinary. Do not add a second mock surface (no fake “investment client” injected only for tests unless that client is the production integration module under test).
- Split coverage, still through that seam:
  - Client tests: URL path `/calculator/roi` vs `/calculator/payback`, `authentication-key` header (not a user Bearer), timeout, JSON body snake_case, `200` payload returned as-is, `validation_error` → `ValueError(message)`, transport/`unauthorized`/5xx/non-JSON → integration error, missing `INVESTMENT_MS_BASE_URL` or timeout setting named in the failure.
  - Tool tests: JSON string and dict inputs both produce one POST of the object; unreadable non-JSON input never calls HTTP and still raises the current “JSON object string” `ValueError`; names and descriptions unchanged; tool functions still wired as the two investment tools.
  - Catalog/kit tests already assert tool membership; they should keep passing without new ChatGPT auth rules.
  - Observability: success still logs `calculate_roi`/`calculate_payback` succeeded; a `validation_error` mapped to `ValueError` still logs a failed tool. Integration failures should also surface as a failed tool line, not as a successful empty answer.
- Prior art: Inventory and Cloudinary integration tests (fake response + recording `requests.request`, missing env named, status `>= 400` becomes the client error). Existing finance tests are the behaviour oracle for success shapes, refusal substrings, and tool registration — keep those assertions at the tool boundary with HTTP scripted, do not keep asserting local arithmetic.
- Do not add live calls to a real calculator service in this gateway’s suite. Scripted HTTP is the contract test here. Arithmetic golden tests (`vp_total` 200, `roi_percent` 33.33, payback month 2 on the 150 / 0.25 / `[125, 156.25]` example) are requirements on the service; this gateway may only assert that a scripted `200` with that payload is returned unchanged.

## Out of Scope

- Implementing the calculator service repository, its deployment, or its own test suite.
- Moving or changing the arithmetic `calculator` tool (AST allowlist, expression limits, local evaluation).
- Changing agent-visible tool names, ChatGPT anonymous/authenticated split, or which Aeko kit receives ROI/payback.
- A committed OpenAPI/YAML contract in this git tree, GitHub Issues on `aether-ai-gateway` as the primary tracker, or committing `.scratch/`.
- Local fallback, retries, HTTP API versioning, user Bearer auth on these paths, camelCase JSON, or merging this contract into the gateway’s public swagger.
- Changing `calculate_roi` / `calculate_payback` to a single combined endpoint.

## Further Notes

- Worked example the service must keep matching (today’s tool tests): request `{ "capex": 150, "wacc_monthly": 0.25, "cash_flows": [125, 156.25] }` → ROI `{ capex: 150, wacc_monthly: 0.25, months: 60, vp_total: 200.0, vpl: 50.0, roi_percent: 33.33, viable: true }` and payback `payback_months: 2` with the same present-value totals.
- Tickets for the gateway client belong next to this spec and as cards on Project 1 view 11. They are not part of this document’s publication.
- Seams for implementers: one — the two tool functions, with HTTP recorded at the shared requests boundary. If that seam is wrong, stop and change this spec before coding.
