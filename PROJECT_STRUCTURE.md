# Project structure and practices

This is the contract for how `aether-ai-gateway` is laid out and how new code
must be written. The README is the onboarding page; this file is the source of
truth for structure and conventions.

`tests/test_code_quality.py` and `tests/test_constants.py` enforce several of
these rules. If a change disagrees with this document, update the tests and
this file in the same change.

## Layout

Domain behavior lives in root packages. HTTP, tools, and the process entrypoint
stay outside those packages.

```text
.
├── user/                      users and memories
├── session/                   conversations and messages
├── improvement_plan/          inventory analysis plans
├── oauth/                     ChatGPT OAuth 2.1
├── upload_ticket/             inventory upload tickets
├── aeko_metrics/              SDK run metrics
├── hub_metrics/               HTTP request metrics
├── cmd/
│   ├── api/
│   │   ├── main.py            FastAPI composition; only Aeko SDK import
│   │   ├── acl/               MCP auth, ChatGPT catalog, identity
│   │   ├── tools/             LangChain tools
│   │   └── integrations/      outbound HTTP and MCP clients
│   └── memory_generator_worker/
├── internal/
│   ├── http/                  FastAPI routers and request models
│   ├── shared/                logging, operations, request log
│   └── observability/         OpenTelemetry
├── tests/
├── .env.example
└── PROJECT_STRUCTURE.md
```

### Domain package shape

Each domain package owns its entities, contracts, service, constants, and
persistence. Typical files:

| File | Role |
| --- | --- |
| `entity.py` | Data types only. No UPPERCASE constants, no re-exports of `constants.py`. |
| `<package>.py` | `IService` / `IRepository` ABCs and domain errors. |
| `service.py` | Business logic against the contracts. |
| `constants.py` | The only module that defines package-level UPPERCASE names. |
| `database/query.py` | MongoDB filters and projections. |
| `database/repository.py` | Persistence implementing `IRepository`. |
| `cache/` | Redis keys, repositories, and TTL helpers when the domain uses Redis. |

Do not put FastAPI routers inside a domain package. Do not import the Aeko SDK
from a domain package.

### Composition

- `cmd/api/main.py` wires MongoDB, Redis, domain services, tools, MCP, and
  lifespan. It is the only module that imports `aeko`.
- `internal/http` exposes HTTP. Handlers depend on service contracts, not on
  SDK types.
- `cmd/api/acl` authenticates ChatGPT MCP, binds identity from the hub JWT and
  ms-auth profile, and builds the FastMCP catalog.
- `cmd/api/tools` adapts domain services into LangChain tools.
- `cmd/api/integrations` talks to Inventory, Auth, Profile, Cloudinary,
  Climatiq, Tavily, Chroma, and the investment calculator service.
- `cmd/memory_generator_worker` is a separate process. Keep its constants in
  `cmd/memory_generator_worker/constants.py`.

### Tests

- Tests live in `tests/` and load `tests/settings.env` with `override=True`.
- Name files `test_<area>.py`. Doubles stay in `tests/` (`fake_aeko.py`,
  `mongo_doubles.py`, `ms_auth_doubles.py`).
- `pytest.ini` disables the debugging plugin because the `cmd` package shadows
  the standard-library module used by `pdb`.

## Practices

### Test-driven development

The tests in `tests/` are written first. Implementation continues until those
tests pass. Do not change a test to match accidental production behavior
without an explicit request.

Run the suite with:

```bash
python -m pytest -q
```

After a change, run the files that cover the behavior you touched. Ask which
`tests/` file to run when that is unclear.

### Documentation in source

- Every Python module under the packages listed in `tests/test_code_quality.py`
  has an English module docstring that states its purpose.
- Every public function, method, and callback (name not starting with `_`) has
  an English docstring.
- Put implementation documentation in those docstrings.
- Do not use `#` comments. `tests/test_code_quality.py` rejects comment tokens.
  Hashes inside strings are allowed.

### Constants

- Each package has one `constants.py`. Define shared configuration and
  meaningful domain values there.
- Do not assign UPPERCASE names in other modules of that package. The only
  exceptions are live MCP session objects (`CHROMA_SESSION`, `MONGO_SESSION`).
- Import constants from `constants.py`. Do not re-export them from `entity.py`,
  `catalog.py`, or other barrels. Unused re-exports break when an unused-import
  cleanup runs.
  - ChatGPT allowlists live in `cmd/api/acl/open_ai/constants.py`.
  - Upload-ticket states live in `upload_ticket/constants.py`.
- Use the environment variable name directly when an alias adds no information.
- Calculator function mappings stay in Python. Investment request schemas
  belong to the calculator service; this gateway forwards the JSON object.

### Environment

- Copy every setting from `.env.example`. Configurable constants have no
  Python fallback; a missing required key raises `KeyError`.
- Each `constants.py` loads the repository-root `.env` with `override=False`,
  using a path relative to the file so launch directory does not matter.
- Restart the process after changing environment values.
- Lists, sets, tuples, and dictionaries use JSON in the environment.
- Log color values are JSON strings containing ANSI escapes. `INDENT` keeps
  its quoted spaces.
- Financial tool descriptions use named placeholders such as
  `{ROI_HORIZON_MONTHS}` and `{ROI_REQUEST_DESCRIPTION}` so they follow the
  numeric settings.
- The Chroma server script path is relative to its MCP package unless an
  absolute path is supplied.
- `AETHER_WEB_SITE_URL` selects the URL used by the Tavily site-map tool.
- MCP sessions stay open for the application lifetime. Set `AEKO_MCP_WARM_UP`
  to `false` to open them on first use.

### Identity, tenancy, and HTTP

- Bind user and company identity from the authenticated token and request
  context. Do not trust model-supplied identity arguments.
- ChatGPT MCP is default-deny: a `tools/call` name that is not in
  `ANONYMOUS_CHATGPT_TOOL_NAMES` requires a hub JWT, Redis session, and live
  ms-auth profile.
- Inventory create uses the bound ms-auth Bearer. Do not add a parallel API
  key on that path.
- HTTP handlers return a stable client error for unexpected failures. Log the
  cause; do not leak internals in the response body.

### Formatting

- Wrap long signatures, calls, and literals so lines stay readable.
- Prefer small, single-purpose functions. Keep FastAPI models next to the
  router that uses them.

### Agent notes

`AGENTS.md` describes the agent workflow. `AGENT_DOCS/` is agent scratch
memory: at most three lines per request, delete outdated notes. Do not treat
`AGENT_DOCS/` as product documentation.
