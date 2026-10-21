"""Verify that authenticated ChatGPT tools challenge unsigned callers with 401."""

from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

MCP_PREFIX = "/ai/mcp"
MCP_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}
RESOURCE_METADATA = (
    "https://aeko.example.com/ai/mcp/.well-known/oauth-protected-resource"
)
AUTHENTICATED_CALLS = (
    ("ask_aeko", {"input": "hi"}),
    ("list_latest_improvement_plans", {"n": 3}),
    ("query_improvement_plan_problems", {"query": "flaring"}),
    ("get_user_profile_by_external_id", {}),
    (
        "analyze_inventory",
        {
            "name": "inv",
            "fileType": "XLSX",
            "file": {
                "download_url": "https://files.chatgpt.example/tmp",
                "file_id": "file_abc",
            },
        },
    ),
)


@pytest.fixture
def oauth_env(monkeypatch):
    """Set OAuth environment variables used by the MCP challenge string."""
    monkeypatch.setenv("OAUTH_SIGNING_KEY", "test-signing-key")
    monkeypatch.setenv("OAUTH_ISSUER", "https://aeko.example.com")
    monkeypatch.setenv("OAUTH_AUDIENCE", "https://aeko.example.com/ai/mcp/")
    monkeypatch.setenv("OAUTH_CLIENT_ID", "chatgpt")
    monkeypatch.setenv("OAUTH_AUTHORIZATION_CODE_TTL_SECONDS", "300")
    monkeypatch.setenv("OAUTH_ACCESS_TOKEN_TTL_SECONDS", "3600")
    monkeypatch.setenv("AUTH_MS_BASE_URL", "http://auth.test")
    monkeypatch.setenv("MS_HTTP_TIMEOUT", "30")


@pytest.fixture(autouse=True)
def stub_ms_auth_profile_resolution(monkeypatch):
    """Resolve MCP Bearer tokens through a stub ms-auth profile."""
    from cmd.api.integrations.profile_api import ProfileError
    from tests.test_oauth import oauth_profile

    def get_profile(token):
        """Return a profile payload or reject unknown tokens."""
        if token in {"not-a-jwt", "expired-token"}:
            raise ProfileError("denied")
        if token.startswith("user-"):
            return oauth_profile(id=int(token.removeprefix("user-")))
        return oauth_profile(id=12345)

    monkeypatch.setattr("cmd.api.acl.ms_auth_security.get_profile", get_profile)


def rpc(method, params=None, id=1):
    """Build a JSON-RPC 2.0 payload for the ChatGPT MCP endpoint."""
    payload = {"jsonrpc": "2.0", "id": id, "method": method}
    if params is not None:
        payload["params"] = params
    return payload


def initialize_body():
    """Return an MCP initialize request ChatGPT sends on a public host."""
    return rpc(
        "initialize",
        {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "chatgpt", "version": "1"},
        },
    )


def call_tool(name, arguments=None, id=1):
    """Return a tools/call JSON-RPC body for the named ChatGPT tool."""
    return rpc("tools/call", {"name": name, "arguments": arguments or {}}, id=id)


def www_authenticate_list(body):
    """Return the mcp/www_authenticate list from a JSON-RPC body, if present."""
    candidates = [body]
    result = body.get("result")
    if isinstance(result, dict):
        candidates.append(result)
        if isinstance(result.get("error"), dict):
            candidates.append(result["error"])
    error = body.get("error")
    if isinstance(error, dict):
        candidates.append(error)
        data = error.get("data")
        if isinstance(data, dict):
            candidates.append(data)
    for candidate in candidates:
        meta = candidate.get("_meta") if isinstance(candidate, dict) else None
        if isinstance(meta, dict) and "mcp/www_authenticate" in meta:
            return meta["mcp/www_authenticate"]
    return None


def hub_bearer(id_external_user=12345, id_external_company=90, ms_auth_access_token="ms-access", sessions=None):
    """Return Authorization headers for a hub JWT with a stored ms-auth session."""
    from cmd.api.acl import mcp_auth
    from oauth.token import encode_access_token
    from tests.test_oauth import InMemorySessions

    token = encode_access_token(id_external_user, id_external_company)
    store = sessions if sessions is not None else InMemorySessions()
    store.save(
        token,
        {
            "ms_auth_access_token": ms_auth_access_token,
            "id_external_user": id_external_user,
            "id_external_company": id_external_company,
        },
        3600,
    )
    mcp_auth.configure(sessions=store)
    return {**MCP_HEADERS, "Authorization": f"Bearer {token}"}, store


def make_client():
    """Build an isolated FastAPI app that only serves the wrapped ChatGPT MCP."""
    from cmd.api.acl.mcp_auth import wrap_mcp_auth
    from cmd.api.acl.open_ai.server import build_mcp_server

    mcp = build_mcp_server()
    wrapped = wrap_mcp_auth(mcp.streamable_http_app())

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Run the FastMCP streamable HTTP session manager for the isolated app."""
        async with mcp.session_manager.run():
            yield

    app = FastAPI(lifespan=lifespan)
    app.mount(MCP_PREFIX, wrapped)
    return TestClient(app, base_url="https://aeko.example.com")


def post_mcp(client, body, headers=None):
    """POST a JSON-RPC payload to the mounted ChatGPT MCP endpoint."""
    return client.post(f"{MCP_PREFIX}/", headers=headers or MCP_HEADERS, json=body)


def assert_unauthorized_challenge(response):
    """Require HTTP 401, WWW-Authenticate, and JSON-RPC mcp/www_authenticate."""
    from cmd.api.acl.mcp_auth import www_authenticate_value

    challenge = www_authenticate_value()
    body = response.json()
    meta = www_authenticate_list(body)
    is_error = False
    if isinstance(body.get("result"), dict) and body["result"].get("isError") is True:
        is_error = True
    if "error" in body:
        is_error = True

    assert response.status_code == 401
    assert response.headers.get("www-authenticate") == challenge
    assert "resource_metadata=" in challenge
    assert "error=" in challenge
    assert "error_description=" in challenge
    assert is_error
    assert isinstance(meta, list) and len(meta) == 1
    assert RESOURCE_METADATA in meta[0]
    assert meta[0] == challenge


def test_www_authenticate_value_uses_the_issuer_protected_resource(oauth_env):
    """Verify that the challenge string points at this API's protected-resource metadata."""
    from cmd.api.acl.mcp_auth import www_authenticate_value

    challenge = www_authenticate_value()
    assert challenge == (
        f'Bearer resource_metadata="{RESOURCE_METADATA}", '
        'scope="mcp", error="insufficient_scope", '
        'error_description="You need to login to continue"'
    )


def test_initialize_without_authorization_is_not_unauthorized(oauth_env):
    """Verify that MCP initialize stays public without a Bearer token."""
    with make_client() as client:
        response = post_mcp(client, initialize_body())

    assert response.status_code != 401
    assert "www-authenticate" not in response.headers
    assert "aeko-chatgpt" in response.text


def test_calculator_without_authorization_is_not_unauthorized(oauth_env):
    """Verify that anonymous FR-004 tools never challenge ChatGPT to Sign in."""
    with make_client() as client:
        response = post_mcp(
            client,
            call_tool("calculator", {"expression": "1+1"}),
        )

    assert response.status_code != 401
    assert "www-authenticate" not in response.headers


def test_calculator_ignores_an_extra_invalid_bearer(oauth_env):
    """Verify that an extra Bearer on an anonymous tool does not trigger 401."""
    headers = {**MCP_HEADERS, "Authorization": "Bearer not-a-jwt"}
    with make_client() as client:
        response = post_mcp(
            client,
            call_tool("calculator", {"expression": "1+1"}),
            headers=headers,
        )

    assert response.status_code != 401


def test_ask_aeko_without_authorization_challenges_sign_in(oauth_env, monkeypatch):
    """Verify that ask_aeko without Bearer returns the ChatGPT Sign in challenge."""
    calls = []

    def fake_ask(*args, **kwargs):
        """Record a domain call that the 401 gate must not make."""
        calls.append((args, kwargs))
        return "should-not-run"

    monkeypatch.setattr("cmd.api.tools.ask_aeko.ask_aeko", fake_ask)

    with make_client() as client:
        response = post_mcp(client, call_tool("ask_aeko", {"input": "hi"}))

    assert_unauthorized_challenge(response)
    assert calls == []


@pytest.mark.parametrize("name, arguments", AUTHENTICATED_CALLS[1:])
def test_authenticated_tools_without_authorization_challenge_sign_in(
    oauth_env, name, arguments, monkeypatch
):
    """Verify that remaining FR-005 tools challenge unsigned callers the same way."""
    monkeypatch.setattr(
        "cmd.api.tools.inventory_tools._analyze_inventory_chatgpt",
        lambda *args, **kwargs: {"id": 1},
    )
    monkeypatch.setattr(
        "cmd.api.tools.inventory_tools.ingest_chatgpt_inventory",
        lambda *args, **kwargs: {"id": 1},
    )
    with make_client() as client:
        response = post_mcp(client, call_tool(name, arguments))

    assert_unauthorized_challenge(response)


def test_invalid_bearer_on_ask_aeko_does_not_run_domain_or_ms_auth(
    oauth_env, monkeypatch
):
    """Verify that an invalid Bearer still 401s without calling ask_aeko or ms-auth."""
    calls = []

    def fake_ask(*args, **kwargs):
        """Record a domain call that the 401 gate must not make."""
        calls.append((args, kwargs))
        return "should-not-run"

    def fake_login(*args, **kwargs):
        """Fail if the MCP gate tries to authenticate through ms-auth."""
        raise AssertionError("ms-auth login must not be called")

    monkeypatch.setattr("cmd.api.tools.ask_aeko.ask_aeko", fake_ask)
    monkeypatch.setattr("cmd.api.integrations.auth_api.login", fake_login)
    monkeypatch.setattr("oauth.service.login", fake_login)

    headers = {**MCP_HEADERS, "Authorization": "Bearer not-a-jwt"}
    with make_client() as client:
        response = post_mcp(
            client,
            call_tool("ask_aeko", {"input": "hi"}),
            headers=headers,
        )

    assert_unauthorized_challenge(response)
    assert calls == []


def test_expired_bearer_on_ask_aeko_does_not_run_domain_or_ms_auth(
    oauth_env, monkeypatch
):
    """Verify that an invalid ms-auth Bearer still 401s without calling ask_aeko."""
    calls = []

    def fake_ask(*args, **kwargs):
        """Record a domain call that the 401 gate must not make."""
        calls.append((args, kwargs))
        return "should-not-run"

    def fake_login(*args, **kwargs):
        """Fail if the MCP gate tries to authenticate through ms-auth login."""
        raise AssertionError("ms-auth login must not be called")

    monkeypatch.setattr("cmd.api.tools.ask_aeko.ask_aeko", fake_ask)
    monkeypatch.setattr("cmd.api.integrations.auth_api.login", fake_login)
    monkeypatch.setattr("oauth.service.login", fake_login)

    headers = {**MCP_HEADERS, "Authorization": "Bearer expired-token"}
    with make_client() as client:
        response = post_mcp(
            client,
            call_tool("ask_aeko", {"input": "hi"}),
            headers=headers,
        )

    assert_unauthorized_challenge(response)
    assert calls == []


def test_valid_token_on_ask_aeko_binds_identity_and_is_not_unauthorized(
    oauth_env, monkeypatch
):
    """Verify that a valid ms-auth token binds the ChatGPT user and does not 401."""
    from cmd.api.acl.open_ai.identity import current_id_external_user
    from cmd.api.tools import ask_aeko as ask_module

    seen = []

    def fake_ask(id_external_user, input, session_name=None):
        """Record the identity the wrapper and middleware bound for this call."""
        seen.append(
            {
                "id_external_user": id_external_user,
                "bound": current_id_external_user(),
                "input": input,
            }
        )
        return "ok"

    monkeypatch.setattr(ask_module, "ask_aeko", fake_ask)
    headers, _store = hub_bearer()

    with make_client() as client:
        initialized = post_mcp(client, initialize_body(), headers=headers)
        session = initialized.headers.get("mcp-session-id")
        call_headers = {**headers}
        if session:
            call_headers["mcp-session-id"] = session
        post_mcp(
            client,
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            headers=call_headers,
        )
        response = post_mcp(
            client,
            call_tool("ask_aeko", {"input": "hi"}),
            headers=call_headers,
        )

    assert response.status_code != 401
    assert seen
    assert seen[0]["id_external_user"] == 12345 or seen[0]["bound"] == 12345


def test_ms_auth_jwt_on_ask_aeko_is_unauthorized(oauth_env, monkeypatch):
    """Verify that a raw ms-auth Bearer is not accepted as the ChatGPT MCP token."""
    headers = {**MCP_HEADERS, "Authorization": "Bearer ms-access"}
    with make_client() as client:
        response = post_mcp(client, call_tool("ask_aeko", {"input": "hi"}), headers=headers)
    assert_unauthorized_challenge(response)


def test_hub_jwt_without_session_is_unauthorized(oauth_env):
    """Verify that a valid hub JWT with no Redis session still 401s."""
    from oauth.token import encode_access_token
    from cmd.api.acl import mcp_auth
    from tests.test_oauth import InMemorySessions

    mcp_auth.configure(sessions=InMemorySessions())
    token = encode_access_token(12345, 90)
    headers = {**MCP_HEADERS, "Authorization": f"Bearer {token}"}
    with make_client() as client:
        response = post_mcp(client, call_tool("ask_aeko", {"input": "hi"}), headers=headers)
    assert_unauthorized_challenge(response)


def test_attach_id_external_user_keeps_non_dict_scope_state_attributes():
    """Verify that attach writes identity without replacing a non-dict scope state."""
    from cmd.api.acl.open_ai.identity import attach_id_external_user

    class ScopeState:
        def __init__(self):
            """Hold an existing ASGI attribute that attach must preserve."""
            self.other = "kept"

    state = ScopeState()
    scope = {"state": state}
    attach_id_external_user(scope, 12345)

    assert scope["state"] is state
    assert state.other == "kept"
    assert state.chatgpt_id_external_user == 12345


def test_attach_ms_auth_profile_keeps_non_dict_scope_state_attributes():
    """Verify that attach writes profile without replacing a non-dict scope state."""
    from cmd.api.acl.open_ai.identity import attach_ms_auth_profile

    class ScopeState:
        def __init__(self):
            """Hold an existing ASGI attribute that attach must preserve."""
            self.other = "kept"

    profile = {"id": 12345, "enterprise": {"id": 90}}
    state = ScopeState()
    scope = {"state": state}
    attach_ms_auth_profile(scope, profile)

    assert scope["state"] is state
    assert state.other == "kept"
    assert state.chatgpt_ms_auth_profile == profile


def test_attach_ms_auth_access_token_keeps_non_dict_scope_state_attributes():
    """Verify that attach writes the token without replacing a non-dict scope state."""
    from cmd.api.acl.open_ai.identity import attach_ms_auth_access_token

    class ScopeState:
        def __init__(self):
            """Hold an existing ASGI attribute that attach must preserve."""
            self.other = "kept"

    state = ScopeState()
    scope = {"state": state}
    attach_ms_auth_access_token(scope, "ms-access")

    assert scope["state"] is state
    assert state.other == "kept"
    assert state.chatgpt_ms_auth_access_token == "ms-access"


def test_get_user_profile_with_hub_token_returns_ms_auth_catalog(oauth_env, monkeypatch):
    """Verify that get_user_profile_by_external_id over MCP returns the live ms-auth profile."""
    from cmd.api.tools import mongo_tools
    from user.user import User

    class Users:
        def get_mongo_user(self, identifier):
            """Return the Mongo user for the bound ChatGPT identity."""
            return User(id="u1", id_external_user=identifier, role="analyst", usecase="inventory")

    mongo_tools.configure(users=Users())
    headers, _ = hub_bearer(id_external_user=12345, ms_auth_access_token="ms-access")
    try:
        with make_client() as client:
            initialized = post_mcp(client, initialize_body(), headers=headers)
            session = initialized.headers.get("mcp-session-id")
            call_headers = {**headers}
            if session:
                call_headers["mcp-session-id"] = session
            post_mcp(
                client,
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                headers=call_headers,
            )
            response = post_mcp(
                client,
                call_tool("get_user_profile_by_external_id", {}),
                headers=call_headers,
            )
    finally:
        mongo_tools.configure()

    assert response.status_code != 401
    assert "analyst" in response.text
    assert "Sign in is required" not in response.text


def test_valid_token_without_local_user_is_not_unauthorized(oauth_env):
    """Verify that a valid ms-auth token for a missing local User is not 401."""
    from cmd.api.tools import mongo_tools

    class Users:
        def get_mongo_user(self, identifier):
            """Raise the domain error for a ChatGPT id with no local User."""
            raise ValueError(f"User with id_external_user {identifier} not found.")

    mongo_tools.configure(users=Users())
    headers, _store = hub_bearer(
        id_external_user=99999,
        id_external_company=90,
        ms_auth_access_token="user-99999",
    )
    try:
        with make_client() as client:
            initialized = post_mcp(client, initialize_body(), headers=headers)
            session = initialized.headers.get("mcp-session-id")
            call_headers = {**headers}
            if session:
                call_headers["mcp-session-id"] = session
            post_mcp(
                client,
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                headers=call_headers,
            )
            response = post_mcp(
                client,
                call_tool("get_user_profile_by_external_id", {}),
                headers=call_headers,
            )
    finally:
        mongo_tools.configure()

    assert response.status_code != 401
    assert "www-authenticate" not in response.headers
    assert "not found" in response.text.lower()
    assert '"isError":true' in response.text.replace(" ", "")


def test_mounted_app_challenges_ask_aeko_without_bearer(api_main, oauth_env, monkeypatch):
    """Verify that the production mount wraps MCP with the same 401 gate."""
    calls = []

    def fake_ask(*args, **kwargs):
        """Record a domain call that the 401 gate must not make."""
        calls.append((args, kwargs))
        return "should-not-run"

    monkeypatch.setattr("cmd.api.tools.ask_aeko.ask_aeko", fake_ask)

    with TestClient(api_main.app, base_url="https://aeko.example.com") as client:
        response = post_mcp(client, call_tool("ask_aeko", {"input": "hi"}))

    assert_unauthorized_challenge(response)
    assert calls == []


def test_jsonrpc_batch_containing_ask_aeko_does_not_execute_the_tool(
    oauth_env, monkeypatch
):
    """Verify that a JSON-RPC batch with ask_aeko returns 401 and never runs the tool."""
    calls = []

    def fake_ask(*args, **kwargs):
        """Record a domain call that the 401 gate must not make."""
        calls.append((args, kwargs))
        return "should-not-run"

    monkeypatch.setattr("cmd.api.tools.ask_aeko.ask_aeko", fake_ask)

    batch = [
        call_tool("calculator", {"expression": "1+1"}, id=1),
        call_tool("ask_aeko", {"input": "hi"}, id=2),
    ]
    with make_client() as client:
        response = post_mcp(client, batch)

    assert_unauthorized_challenge(response)
    assert calls == []


def test_non_object_jsonrpc_garbage_is_unauthorized(oauth_env, monkeypatch):
    """Verify that non-object MCP JSON is rejected with 401 and not forwarded unsigned."""
    calls = []

    def fake_ask(*args, **kwargs):
        """Record a domain call that the 401 gate must not make."""
        calls.append((args, kwargs))
        return "should-not-run"

    monkeypatch.setattr("cmd.api.tools.ask_aeko.ask_aeko", fake_ask)

    with make_client() as client:
        response = client.post(
            f"{MCP_PREFIX}/",
            headers=MCP_HEADERS,
            content=b"not-json",
        )

    assert_unauthorized_challenge(response)
    assert calls == []


def test_catalog_tool_omitted_from_old_allowlist_still_requires_identity(
    oauth_env, monkeypatch
):
    """Verify that an authenticated catalog tool still 401s unsigned when omitted from AUTHENTICATED_CHATGPT_TOOL_NAMES."""
    monkeypatch.setattr(
        "cmd.api.acl.mcp_auth.AUTHENTICATED_CHATGPT_TOOL_NAMES",
        set(),
        raising=False,
    )
    calls = []

    def fake_ask(*args, **kwargs):
        """Record a domain call that the 401 gate must not make."""
        calls.append((args, kwargs))
        return "should-not-run"

    monkeypatch.setattr("cmd.api.tools.ask_aeko.ask_aeko", fake_ask)

    with make_client() as client:
        response = post_mcp(client, call_tool("ask_aeko", {"input": "hi"}))

    assert_unauthorized_challenge(response)
    assert calls == []


def test_unknown_tools_call_without_authorization_challenges_sign_in(
    oauth_env, monkeypatch
):
    """Verify that a tools/call name outside ANONYMOUS_CHATGPT_TOOL_NAMES is 401 unsigned."""
    calls = []

    def fake_ask(*args, **kwargs):
        """Record a domain call that the 401 gate must not make."""
        calls.append((args, kwargs))
        return "should-not-run"

    monkeypatch.setattr("cmd.api.tools.ask_aeko.ask_aeko", fake_ask)

    with make_client() as client:
        response = post_mcp(client, call_tool("not_in_old_allowlist", {}))

    assert_unauthorized_challenge(response)
    assert calls == []


def test_oversized_mcp_body_is_rejected(oauth_env, monkeypatch):
    """Verify that an MCP POST over MCP_MAX_BODY_BYTES is rejected without running tools."""
    from cmd.api.acl.mcp_auth import MCP_MAX_BODY_BYTES

    calls = []

    def fake_calc(*args, **kwargs):
        """Record a calculator call that an oversized body must not reach."""
        calls.append((args, kwargs))
        return "1"

    monkeypatch.setattr("cmd.api.tools.calculator._calculate", fake_calc)

    padding = "0" * MCP_MAX_BODY_BYTES
    with make_client() as client:
        response = client.post(
            f"{MCP_PREFIX}/",
            headers=MCP_HEADERS,
            json=call_tool("calculator", {"expression": padding}),
        )

    assert response.status_code in (413, 401)
    assert calls == []


def test_fastmcp_enables_dns_rebinding_protection(oauth_env):
    """Verify that the ChatGPT FastMCP server enables DNS rebinding protection."""
    from cmd.api.acl.open_ai.server import build_mcp_server

    settings = build_mcp_server().settings.transport_security
    assert settings is not None
    assert settings.enable_dns_rebinding_protection is True
