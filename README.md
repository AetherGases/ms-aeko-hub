# aether-ai-gateway

HTTP API connecting Aether applications to the AI core for conversations,
inventory reports, user memories, and request and agent metrics.

Domain behavior lives in `user`, `session`, `improvement_plan`, `hub_metrics`,
and `aeko_metrics`. Each domain owns its entities, contracts, services, and
persistence. HTTP handlers live in `internal/http`; `cmd/api/main.py` composes
the application and is the only module that imports the Aeko SDK.

Configure the environment using `.env.example`. The application captures its
database and SDK settings after loading the environment. Empty optional model
and token settings use SDK defaults.
`AETHER_WEB_SITE_URL` selects the URL used by the Tavily site-map tool.

Each `constants.py` loads `.env` from the repository root without overriding
existing process environment variables. Copy all settings from `.env.example`
when setting up a deployment; configurable constants have no Python fallback
values. Restart the application after changing them.

Lists, sets, tuples, and dictionaries use JSON in the environment. Log color
values are JSON strings containing ANSI escapes; `INDENT` preserves its quoted
spaces. The Chroma server script path is relative to its MCP package unless
an absolute path is supplied. Financial descriptions use named placeholders
such as `{ROI_HORIZON_MONTHS}` and `{ROI_REQUEST_DESCRIPTION}` so they follow
the numeric settings. Calculator function mappings and request field schemas
remain in Python.

MCP sessions remain open for the application lifetime. Set `AEKO_MCP_WARM_UP`
to `false` to open them on first use. Chroma requires the tenant, database,
and API key and uses the embedding model configured for the `gases-info` corpus.
Climatiq uses its search and estimate data endpoints through HTTP.

Python modules and public functions must have English docstrings describing
their purpose. Keep implementation documentation in docstrings and omit code
comments. Use constants for shared configuration or meaningful domain values;
use environment variable names directly where an alias adds no information.

Run the full suite with `python -m pytest -q`. Tests load `tests/settings.env`
to isolate constants from local settings, use SDK and database doubles,
and disable MCP warm-up. `pytest.ini` disables the debugging plugin because the
application's `cmd` package shadows the standard-library module used by `pdb`.
`tests/test_code_quality.py` checks docstring presence and comment tokens;
English wording and documentation accuracy require review.
