"""Verify OAuth 2.1 authorization-code and PKCE S256 token issuance."""

import base64
import hashlib
import json
from urllib.parse import parse_qs, urlparse

import pytest

from tests.conftest import FakeRedis


class InMemoryCodes:
    def __init__(self):
        self._items = {}
        self.ttls = {}

    def save(self, code, document, ttl):
        """Persist an authorization code document for the configured TTL."""
        self._items[code] = document
        self.ttls[code] = ttl

    def pop(self, code):
        """Remove and return the stored authorization code document, if present."""
        self.ttls.pop(code, None)
        return self._items.pop(code, None)


class InMemorySessions:
    def __init__(self):
        self._items = {}
        self.ttls = {}

    def save(self, access_token, document, ttl):
        """Persist a hub-token session for the configured TTL."""
        self._items[access_token] = document
        self.ttls[access_token] = ttl

    def get(self, access_token):
        """Return the stored session document, if present."""
        return self._items.get(access_token)


def s256(verifier: str) -> str:
    """Return the S256 code challenge for a PKCE verifier."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


VERIFIER = "verifier-12345678901234567890123456789012"
CHATGPT_REDIRECT = "https://chatgpt.com/connector_platform_oauth_redirect"
CIMD_CLIENT_ID = "https://chatgpt.com/oauth/client.json"
OAUTH_ENTERPRISE = {
    "id": 90,
    "name": "Aether Industria SA",
    "tradeName": "Aether",
    "cnpj": "12345678000199",
}


def oauth_profile(**overrides):
    """Build a minimal ms-auth profile payload for OAuth tests."""

    payload = {"id": 1, "enterprise": OAUTH_ENTERPRISE}
    payload.update(overrides)
    return payload


@pytest.fixture
def oauth_env(monkeypatch):
    """Set OAuth authorization-server environment variables for the test."""
    monkeypatch.setenv("OAUTH_SIGNING_KEY", "test-signing-key")
    monkeypatch.setenv("OAUTH_ISSUER", "https://aeko.example.com")
    monkeypatch.setenv("OAUTH_AUDIENCE", "https://aeko.example.com/ai/mcp/")
    monkeypatch.setenv("OAUTH_CLIENT_ID", "chatgpt")
    monkeypatch.setenv("OAUTH_AUTHORIZATION_CODE_TTL_SECONDS", "300")
    monkeypatch.setenv("OAUTH_ACCESS_TOKEN_TTL_SECONDS", "3600")


def authenticated_login(email, password):
    """Return a successful auth-microservice payload for the given credentials."""
    return {"authenticated": True, "accessToken": "ms-access", "refreshToken": "ms-refresh"}


def stub_sign_in(monkeypatch, profile=None, profile_error=None):
    """Replace login and get_profile with scripted OAuth Sign in collaborators."""
    monkeypatch.setattr("oauth.service.login", authenticated_login)

    def get_profile(access_token):
        """Return or raise the scripted profile payload."""
        if profile_error is not None:
            raise profile_error
        return profile if profile is not None else oauth_profile()

    monkeypatch.setattr("oauth.service.get_profile", get_profile)


def authorize(
    service,
    *,
    client_id="chatgpt",
    redirect_uri=CHATGPT_REDIRECT,
    state="xyz",
    code_challenge=None,
    code_challenge_method="S256",
    resource=None,
):
    """Run authorize with ChatGPT PKCE defaults for the test."""
    return service.authorize(
        "caio@example.com",
        "secret",
        client_id=client_id,
        redirect_uri=redirect_uri,
        state=state,
        code_challenge=s256(VERIFIER) if code_challenge is None else code_challenge,
        code_challenge_method=code_challenge_method,
        resource=resource,
    )


def test_access_token_round_trips_the_profile_id(oauth_env):
    """Verify that access token round trips user and company claims."""
    from oauth.token import AccessTokenClaims, decode_access_token, encode_access_token

    token = encode_access_token(1, 90)
    assert decode_access_token(token) == AccessTokenClaims(1, 90)
    assert token.count(".") == 2


def test_access_token_is_rejected_when_expired(oauth_env, monkeypatch):
    """Verify that access token is rejected when expired."""
    from oauth.token import decode_access_token, encode_access_token

    monkeypatch.setattr("oauth.token.time.time", lambda: 1_000_000)
    token = encode_access_token(1, 90)
    monkeypatch.setattr("oauth.token.time.time", lambda: 1_000_000 + 3601)
    with pytest.raises(ValueError):
        decode_access_token(token)


def test_authorize_calls_auth_then_profile_and_does_not_return_ms_tokens(
    monkeypatch, oauth_env
):
    """Verify that authorize calls auth then profile and does not return ms tokens."""
    from oauth.service import Service

    order = []

    def login(email, password):
        """Record a login call and return a successful auth-microservice payload."""
        order.append(("login", email, password))
        return {
            "authenticated": True,
            "accessToken": "ms-access",
            "refreshToken": "ms-refresh",
            "email": email,
        }

    def get_profile(access_token):
        """Record a profile call and return a profile payload with extra fields."""
        order.append(("profile", access_token))
        return oauth_profile(cpf="12345678901", image={"path": "/x"})

    monkeypatch.setattr("oauth.service.login", login)
    monkeypatch.setattr("oauth.service.get_profile", get_profile)
    codes = InMemoryCodes()
    redirect = Service(codes).authorize(
        "caio@example.com",
        "secret",
        client_id="chatgpt",
        redirect_uri="https://chatgpt.com/connector_platform_oauth_redirect",
        state="xyz",
        code_challenge=s256("verifier-12345678901234567890123456789012"),
        code_challenge_method="S256",
    )
    assert order == [("login", "caio@example.com", "secret"), ("profile", "ms-access")]
    assert "ms-access" not in redirect
    assert "ms-refresh" not in redirect
    assert "cpf" not in redirect
    assert "code=" in redirect and "state=xyz" in redirect


def test_authorize_applies_sign_in_profile_after_authentication(monkeypatch, oauth_env):
    """Verify that authorize syncs the Mongo user from ms-auth after Sign in."""
    from oauth.service import Service

    calls = []

    class Users:
        def apply_sign_in_profile(self, id_external_user, *, ms_auth_profile=None):
            """Record the Sign in profile sync."""
            calls.append(
                (
                    "apply_sign_in_profile",
                    id_external_user,
                    ms_auth_profile,
                )
            )

    stub_sign_in(monkeypatch, profile=oauth_profile(id=42))
    authorize(Service(InMemoryCodes(), Users()))

    assert calls == [
        (
            "apply_sign_in_profile",
            42,
            oauth_profile(id=42),
        ),
    ]


def test_authorize_skips_provisioning_when_users_service_is_not_configured(monkeypatch, oauth_env):
    """Verify that authorize still works when no Mongo users service is wired."""
    from oauth.service import Service

    stub_sign_in(monkeypatch, profile=oauth_profile(id=7))
    redirect = authorize(Service(InMemoryCodes()))
    assert "code=" in redirect


@pytest.mark.parametrize(
    "payload",
    [
        {"authenticated": False, "accessToken": "ms-access"},
        {"authenticated": True},
        {"authenticated": True, "accessToken": ""},
    ],
)
def test_authorize_does_not_call_profile_when_login_is_not_authenticated(
    monkeypatch, oauth_env, payload
):
    """Verify that authorize does not call profile when login is not authenticated."""
    from oauth.service import Service

    monkeypatch.setattr("oauth.service.login", lambda email, password: payload)
    called = []
    monkeypatch.setattr("oauth.service.get_profile", lambda token: called.append(token))
    with pytest.raises(ValueError):
        Service(InMemoryCodes()).authorize(
            "caio@example.com",
            "secret",
            client_id="chatgpt",
            redirect_uri="https://chatgpt.com/connector_platform_oauth_redirect",
            state="xyz",
            code_challenge=s256("verifier-12345678901234567890123456789012"),
            code_challenge_method="S256",
        )
    assert called == []


def test_exchange_returns_this_api_access_token(monkeypatch, oauth_env):
    """Verify that exchange returns this API's access token, not the ms-auth token."""
    from oauth.service import Service
    from oauth.token import decode_access_token

    monkeypatch.setattr(
        "oauth.service.login",
        lambda email, password: {"authenticated": True, "accessToken": "ms-access"},
    )
    monkeypatch.setattr("oauth.service.get_profile", lambda token: oauth_profile(id=7))
    sessions = InMemorySessions()
    service = Service(InMemoryCodes(), sessions=sessions)
    verifier = "verifier-12345678901234567890123456789012"
    location = service.authorize(
        "caio@example.com",
        "secret",
        client_id="chatgpt",
        redirect_uri="https://chatgpt.com/connector_platform_oauth_redirect",
        state="s",
        code_challenge=s256(verifier),
        code_challenge_method="S256",
    )
    code = parse_qs(urlparse(location).query)["code"][0]
    body = service.exchange(
        code,
        client_id="chatgpt",
        redirect_uri="https://chatgpt.com/connector_platform_oauth_redirect",
        code_verifier=verifier,
    )
    assert set(body) == {"access_token", "token_type", "expires_in"}
    assert body["token_type"] == "Bearer"
    assert body["expires_in"] == 3600
    assert body["access_token"] != "ms-access"
    claims = decode_access_token(body["access_token"])
    assert claims.id_external_user == 7
    assert claims.id_external_company == 90
    stored = sessions.get(body["access_token"])
    assert stored == {
        "ms_auth_access_token": "ms-access",
        "id_external_user": 7,
        "id_external_company": 90,
    }
    assert sessions.ttls[body["access_token"]] == 3600


def test_exchange_uses_expires_in_from_login_payload(monkeypatch, oauth_env):
    """Verify that exchange forwards ms-auth expiresIn when login provides it."""
    from oauth.service import Service

    monkeypatch.setattr(
        "oauth.service.login",
        lambda email, password: {
            "authenticated": True,
            "accessToken": "ms-access",
            "expiresIn": 1800,
        },
    )
    monkeypatch.setattr("oauth.service.get_profile", lambda token: oauth_profile(id=7))
    sessions = InMemorySessions()
    service = Service(InMemoryCodes(), sessions=sessions)
    verifier = "verifier-12345678901234567890123456789012"
    location = service.authorize(
        "caio@example.com",
        "secret",
        client_id="chatgpt",
        redirect_uri="https://chatgpt.com/connector_platform_oauth_redirect",
        state="s",
        code_challenge=s256(verifier),
        code_challenge_method="S256",
    )
    code = parse_qs(urlparse(location).query)["code"][0]
    body = service.exchange(
        code,
        client_id="chatgpt",
        redirect_uri="https://chatgpt.com/connector_platform_oauth_redirect",
        code_verifier=verifier,
    )
    assert body["expires_in"] == 1800
    assert sessions.ttls[body["access_token"]] == 1800
    payload_b64 = body["access_token"].split(".")[1]
    padding = "=" * (-len(payload_b64) % 4)
    payload = json.loads(base64.urlsafe_b64decode(payload_b64 + padding))
    assert payload["exp"] - payload["iat"] == 1800


def test_authorize_redirect_includes_issuer_and_state(monkeypatch, oauth_env):
    """Verify that authorize redirects with code, state, and the configured issuer."""
    from oauth.constants import OAUTH_ISSUER
    from oauth.service import Service

    stub_sign_in(monkeypatch)
    location = authorize(Service(InMemoryCodes()), state="xyz")
    query = parse_qs(urlparse(location).query)
    assert query["state"] == ["xyz"]
    assert query["iss"] == [OAUTH_ISSUER]
    assert query["code"][0]


def test_authorize_persists_only_oauth_code_fields(monkeypatch, oauth_env):
    """Verify that the stored authorization code keeps only OAuth fields and the profile id."""
    from oauth.service import Service

    stub_sign_in(
        monkeypatch,
        profile=oauth_profile(id=1, cpf="12345678901", email="caio@example.com"),
    )
    codes = InMemoryCodes()
    location = authorize(Service(codes))
    code = parse_qs(urlparse(location).query)["code"][0]
    assert codes.ttls[code] == 300
    document = codes.pop(code)
    assert document == {
        "id_external_user": 1,
        "id_external_company": 90,
        "ms_auth_access_token": "ms-access",
        "ms_auth_access_token_expires_in": 3600,
        "client_id": "chatgpt",
        "redirect_uri": CHATGPT_REDIRECT,
        "code_challenge": s256(VERIFIER),
        "code_challenge_method": "S256",
    }


def test_authorize_fails_when_get_profile_raises(monkeypatch, oauth_env):
    """Verify that Sign in fails when the profile microservice raises."""
    from oauth.service import Service

    stub_sign_in(monkeypatch, profile_error=RuntimeError("profile down"))
    with pytest.raises(ValueError):
        authorize(Service(InMemoryCodes()))


def test_authorize_fails_when_profile_id_is_invalid(monkeypatch, oauth_env):
    """Verify that Sign in fails when the profile id cannot be used as id_external_user."""
    from oauth.service import Service

    stub_sign_in(monkeypatch, profile={"id": True})
    with pytest.raises(ValueError):
        authorize(Service(InMemoryCodes()))


def test_authorize_rejects_non_s256_code_challenge_method(monkeypatch, oauth_env):
    """Verify that Sign in fails when the PKCE method is not S256."""
    from oauth.service import Service

    called = []
    monkeypatch.setattr("oauth.service.login", lambda email, password: called.append("login"))
    with pytest.raises(ValueError):
        authorize(Service(InMemoryCodes()), code_challenge_method="plain")
    assert called == []


def test_authorize_accepts_chatgpt_cimd_client_id(monkeypatch, oauth_env):
    """Verify that ChatGPT client_id metadata document URLs are accepted."""
    from oauth.service import Service

    stub_sign_in(monkeypatch)
    location = authorize(Service(InMemoryCodes()), client_id=CIMD_CLIENT_ID)
    query = parse_qs(urlparse(location).query)
    assert query["code"][0]
    assert query["state"] == ["xyz"]


def test_authorize_rejects_unknown_client_id(monkeypatch, oauth_env):
    """Verify that Sign in fails when client_id is not chatgpt or a ChatGPT CIMD URL."""
    from oauth.service import Service

    called = []
    monkeypatch.setattr("oauth.service.login", lambda email, password: called.append("login"))
    with pytest.raises(ValueError):
        authorize(Service(InMemoryCodes()), client_id="evil")
    assert called == []


def test_authorize_rejects_unknown_redirect_uri(monkeypatch, oauth_env):
    """Verify that Sign in fails when redirect_uri is not an accepted ChatGPT or localhost URI."""
    from oauth.service import Service

    called = []
    monkeypatch.setattr("oauth.service.login", lambda email, password: called.append("login"))
    with pytest.raises(ValueError):
        authorize(
            Service(InMemoryCodes()),
            redirect_uri="https://evil.example/callback",
        )
    assert called == []


def test_exchange_rejects_mismatched_pkce_verifier(monkeypatch, oauth_env):
    """Verify that token exchange fails when the PKCE verifier does not match."""
    from oauth.service import Service

    stub_sign_in(monkeypatch)
    service = Service(InMemoryCodes(), sessions=InMemorySessions())
    location = authorize(service)
    code = parse_qs(urlparse(location).query)["code"][0]
    with pytest.raises(ValueError):
        service.exchange(
            code,
            client_id="chatgpt",
            redirect_uri=CHATGPT_REDIRECT,
            code_verifier="other-verifier-123456789012345678901234",
        )


def test_exchange_rejects_reused_authorization_code(monkeypatch, oauth_env):
    """Verify that token exchange fails when the authorization code is reused."""
    from oauth.service import Service

    stub_sign_in(monkeypatch)
    service = Service(InMemoryCodes(), sessions=InMemorySessions())
    location = authorize(service)
    code = parse_qs(urlparse(location).query)["code"][0]
    service.exchange(
        code,
        client_id="chatgpt",
        redirect_uri=CHATGPT_REDIRECT,
        code_verifier=VERIFIER,
    )
    with pytest.raises(ValueError):
        service.exchange(
            code,
            client_id="chatgpt",
            redirect_uri=CHATGPT_REDIRECT,
            code_verifier=VERIFIER,
        )


def test_exchange_accepts_resource_equal_to_audience(monkeypatch, oauth_env):
    """Verify that exchange still returns the hub token when resource matches the audience."""
    from oauth.constants import OAUTH_AUDIENCE
    from oauth.service import Service
    from oauth.token import decode_access_token

    stub_sign_in(monkeypatch, profile=oauth_profile(id=7))
    service = Service(InMemoryCodes(), sessions=InMemorySessions())
    location = authorize(service, resource=OAUTH_AUDIENCE)
    code = parse_qs(urlparse(location).query)["code"][0]
    body = service.exchange(
        code,
        client_id="chatgpt",
        redirect_uri=CHATGPT_REDIRECT,
        code_verifier=VERIFIER,
        resource=OAUTH_AUDIENCE,
    )
    assert body["access_token"] != "ms-access"
    assert decode_access_token(body["access_token"]).id_external_user == 7


def test_exchange_rejects_resource_that_is_not_the_audience(monkeypatch, oauth_env):
    """Verify that a resource other than the configured audience is rejected."""
    from oauth.service import Service

    stub_sign_in(monkeypatch)
    service = Service(InMemoryCodes(), sessions=InMemorySessions())
    location = authorize(service)
    code = parse_qs(urlparse(location).query)["code"][0]
    with pytest.raises(ValueError):
        service.exchange(
            code,
            client_id="chatgpt",
            redirect_uri=CHATGPT_REDIRECT,
            code_verifier=VERIFIER,
            resource="https://evil.example/mcp/",
        )


def test_session_repository_saves_and_gets_by_access_token():
    """Verify that the session repository round-trips a hub-token document."""
    from oauth.cache.session_repository import Repository

    redis = FakeRedis()
    repository = Repository(redis)
    repository.save(
        "hub.jwt",
        {"ms_auth_access_token": "ms-access", "id_external_user": 7, "id_external_company": 90},
        1800,
    )
    assert repository.get("hub.jwt") == {
        "ms_auth_access_token": "ms-access",
        "id_external_user": 7,
        "id_external_company": 90,
    }
    assert repository.get("missing") is None


def test_redis_repository_saves_and_pops_authorization_codes(oauth_env):
    """Verify that Redis stores authorization codes under oauth:code:{code} with the TTL."""
    from oauth.cache.key import code_key
    from oauth.cache.repository import Repository
    from oauth.constants import OAUTH_AUTHORIZATION_CODE_TTL_SECONDS

    redis = FakeRedis()
    repository = Repository(redis)
    document = {
        "id_external_user": 1,
        "client_id": "chatgpt",
        "redirect_uri": CHATGPT_REDIRECT,
        "code_challenge": s256(VERIFIER),
        "code_challenge_method": "S256",
    }
    repository.save("opaque-code", document, OAUTH_AUTHORIZATION_CODE_TTL_SECONDS)
    key = code_key("opaque-code")
    assert key == "oauth:code:opaque-code"
    assert redis.expirations[key] == 300
    assert repository.pop("opaque-code") == document
    assert repository.pop("opaque-code") is None


def test_redis_repository_pop_uses_atomic_getdel(oauth_env):
    """Verify that pop consumes the code with a single Redis GETDEL."""
    from oauth.cache.repository import Repository
    from oauth.constants import OAUTH_AUTHORIZATION_CODE_TTL_SECONDS

    redis = FakeRedis()
    commands = []
    original_get = redis.get
    original_delete = redis.delete

    def get(key):
        """Record a GET and return the stored value."""
        commands.append("GET")
        return original_get(key)

    def delete(key):
        """Record a DELETE and remove the stored value."""
        commands.append("DELETE")
        return original_delete(key)

    def getdel(key):
        """Record a GETDEL and consume the stored value."""
        commands.append("GETDEL")
        value = original_get(key)
        original_delete(key)
        return value

    redis.get = get
    redis.delete = delete
    redis.getdel = getdel
    repository = Repository(redis)
    document = {
        "id_external_user": 1,
        "client_id": "chatgpt",
        "redirect_uri": CHATGPT_REDIRECT,
        "code_challenge": s256(VERIFIER),
        "code_challenge_method": "S256",
    }
    repository.save("opaque-code", document, OAUTH_AUTHORIZATION_CODE_TTL_SECONDS)
    commands.clear()
    assert repository.pop("opaque-code") == document
    assert commands == ["GETDEL"]
    assert repository.pop("opaque-code") is None
