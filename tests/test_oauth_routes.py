"""Verify OAuth 2.1 HTTP routes for Sign in, token exchange, and discovery."""

import base64
import hashlib
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


CHATGPT_REDIRECT = "https://chatgpt.com/connector_platform_oauth_redirect"
VERIFIER = "verifier-12345678901234567890123456789012"
AUTHORIZE_PATH = "/ai/oauth/authorize"
TOKEN_PATH = "/ai/oauth/token"
ISSUER = "https://aeko.example.com"
AUDIENCE = "https://aeko.example.com/ai/mcp/"


def s256(verifier: str) -> str:
    """Return the S256 code challenge for a PKCE verifier."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


@pytest.fixture
def oauth_env(monkeypatch):
    """Set OAuth authorization-server environment variables for the test."""
    monkeypatch.setenv("OAUTH_SIGNING_KEY", "test-signing-key")
    monkeypatch.setenv("OAUTH_ISSUER", ISSUER)
    monkeypatch.setenv("OAUTH_AUDIENCE", AUDIENCE)
    monkeypatch.setenv("OAUTH_CLIENT_ID", "chatgpt")
    monkeypatch.setenv("OAUTH_AUTHORIZATION_CODE_TTL_SECONDS", "300")
    monkeypatch.setenv("OAUTH_ACCESS_TOKEN_TTL_SECONDS", "3600")


class StubOAuthService:
    def __init__(self, authorize_error=None, exchange_error=None):
        self.authorize_error = authorize_error
        self.exchange_error = exchange_error
        self.authorize_calls = []
        self.exchange_calls = []

    def authorize(
        self,
        email,
        password,
        *,
        client_id,
        redirect_uri,
        state,
        code_challenge,
        code_challenge_method,
        resource=None,
    ):
        """Record authorize arguments and return a redirect or raise the scripted error."""
        self.authorize_calls.append(
            {
                "email": email,
                "password": password,
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "state": state,
                "code_challenge": code_challenge,
                "code_challenge_method": code_challenge_method,
                "resource": resource,
            }
        )
        if self.authorize_error is not None:
            raise self.authorize_error
        return f"{redirect_uri}?code=opaque-code&state={state}&iss={ISSUER}"

    def exchange(self, code, *, client_id, redirect_uri, code_verifier, resource=None):
        """Record token-exchange arguments and return a token body or raise the scripted error."""
        self.exchange_calls.append(
            {
                "code": code,
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "code_verifier": code_verifier,
                "resource": resource,
            }
        )
        if self.exchange_error is not None:
            raise self.exchange_error
        return {
            "access_token": "this-api-token",
            "token_type": "Bearer",
            "expires_in": 3600,
        }


def authorize_query(**overrides):
    """Return ChatGPT authorize query parameters for the test."""
    query = {
        "response_type": "code",
        "client_id": "chatgpt",
        "redirect_uri": CHATGPT_REDIRECT,
        "state": "xyz",
        "code_challenge": s256(VERIFIER),
        "code_challenge_method": "S256",
        "resource": AUDIENCE,
    }
    query.update(overrides)
    return query


def authorize_form(**overrides):
    """Return a Sign in form body for POST authorize."""
    body = {
        "email": "caio@example.com",
        "password": "secret",
        "client_id": "chatgpt",
        "redirect_uri": CHATGPT_REDIRECT,
        "state": "xyz",
        "code_challenge": s256(VERIFIER),
        "code_challenge_method": "S256",
        "resource": AUDIENCE,
    }
    body.update(overrides)
    return body


def build_client(service):
    """Build a TestClient that only includes the OAuth router and a stub service."""
    from internal.http import oauth_handlers

    app = FastAPI()
    app.include_router(oauth_handlers.router)
    app.state.oauth = service
    return TestClient(app, base_url=ISSUER)


def test_authorization_server_metadata(oauth_env):
    """Verify that authorization-server metadata advertises PKCE S256 and the authorize/token paths."""
    response = build_client(StubOAuthService()).get("/.well-known/oauth-authorization-server")
    body = response.json()
    assert response.status_code == 200
    assert body["issuer"] == ISSUER
    assert body["authorization_endpoint"].endswith("/ai/oauth/authorize")
    assert body["token_endpoint"].endswith("/ai/oauth/token")
    assert body["code_challenge_methods_supported"] == ["S256"]
    assert body["response_types_supported"] == ["code"]
    assert body["grant_types_supported"] == ["authorization_code"]
    assert body["token_endpoint_auth_methods_supported"] == ["none"]
    assert body["client_id_metadata_document_supported"] is True
    assert body["authorization_response_iss_parameter_supported"] is True


def test_protected_resource_metadata(oauth_env):
    """Verify that protected-resource metadata names this API as the MCP resource."""
    response = build_client(StubOAuthService()).get("/.well-known/oauth-protected-resource")
    body = response.json()
    assert response.status_code == 200
    assert body["resource"] == AUDIENCE
    assert body["authorization_servers"] == [ISSUER]
    assert body["bearer_methods_supported"] == ["header"]
    assert body["scopes_supported"] == ["mcp"]


def test_get_authorize_returns_sign_in_html(oauth_env):
    """Verify that GET authorize returns Sign in HTML with credentials and hidden OAuth fields."""
    query = authorize_query()
    response = build_client(StubOAuthService()).get(AUTHORIZE_PATH, params=query)
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    html = response.text
    assert 'name="email"' in html
    assert 'name="password"' in html
    assert 'name="role"' not in html
    assert 'name="usecase"' not in html
    assert 'type="password"' in html
    assert 'name="client_id"' in html
    assert 'name="redirect_uri"' in html
    assert 'name="state"' in html
    assert 'name="code_challenge"' in html
    assert 'name="code_challenge_method"' in html
    assert query["client_id"] in html
    assert query["redirect_uri"] in html
    assert query["state"] in html
    assert query["code_challenge"] in html
    assert query["code_challenge_method"] in html
    assert "accessToken" not in html
    assert "refreshToken" not in html
    assert "cpf" not in html
    assert "Entre na sua conta" in html
    assert f'action="{ISSUER}{AUTHORIZE_PATH}"' in html


def test_protected_resource_metadata_at_mcp_path(oauth_env):
    """Verify that protected-resource metadata is also served on the MCP resource path."""
    response = build_client(StubOAuthService()).get(
        "/ai/mcp/.well-known/oauth-protected-resource"
    )
    body = response.json()
    assert response.status_code == 200
    assert body["resource"] == AUDIENCE
    assert body["authorization_servers"] == [ISSUER]


def test_post_authorize_redirects_with_code_state_and_iss(oauth_env):
    """Verify that POST authorize redirects to the client with code, state, and iss."""
    service = StubOAuthService()
    response = build_client(service).post(
        AUTHORIZE_PATH,
        data=authorize_form(),
        follow_redirects=False,
    )
    assert response.status_code == 302
    location = response.headers["location"]
    parsed = urlparse(location)
    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == CHATGPT_REDIRECT
    query = parse_qs(parsed.query)
    assert query["code"] == ["opaque-code"]
    assert query["state"] == ["xyz"]
    assert query["iss"] == [ISSUER]
    assert service.authorize_calls[0]["email"] == "caio@example.com"
    assert service.authorize_calls[0]["password"] == "secret"


def test_post_authorize_failed_login_returns_html_without_code(oauth_env, monkeypatch):
    """Verify that failed login returns 401 HTML without a Location code and does not call profile."""
    called = []
    monkeypatch.setattr(
        "oauth.service.get_profile",
        lambda token: called.append(token),
    )
    service = StubOAuthService(authorize_error=ValueError("Sign in failed."))
    response = build_client(service).post(
        AUTHORIZE_PATH,
        data=authorize_form(),
        follow_redirects=False,
    )
    assert response.status_code == 401
    assert "text/html" in response.headers["content-type"]
    assert "location" not in {key.lower() for key in response.headers}
    assert "code=" not in response.text
    assert called == []
    assert len(service.authorize_calls) == 1


def test_post_token_returns_bearer_access_token(oauth_env):
    """Verify that the token endpoint exchanges an authorization code for this API's Bearer token."""
    service = StubOAuthService()
    response = build_client(service).post(
        TOKEN_PATH,
        data={
            "grant_type": "authorization_code",
            "code": "opaque-code",
            "client_id": "chatgpt",
            "redirect_uri": CHATGPT_REDIRECT,
            "code_verifier": VERIFIER,
            "resource": AUDIENCE,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body == {
        "access_token": "this-api-token",
        "token_type": "Bearer",
        "expires_in": 3600,
    }
    assert service.exchange_calls == [
        {
            "code": "opaque-code",
            "client_id": "chatgpt",
            "redirect_uri": CHATGPT_REDIRECT,
            "code_verifier": VERIFIER,
            "resource": AUDIENCE,
        }
    ]


def test_post_token_rejects_invalid_code(oauth_env):
    """Verify that an invalid authorization code or PKCE verifier returns HTTP 400."""
    service = StubOAuthService(exchange_error=ValueError("Invalid authorization code."))
    response = build_client(service).post(
        TOKEN_PATH,
        data={
            "grant_type": "authorization_code",
            "code": "missing",
            "client_id": "chatgpt",
            "redirect_uri": CHATGPT_REDIRECT,
            "code_verifier": VERIFIER,
        },
    )
    assert response.status_code == 400
