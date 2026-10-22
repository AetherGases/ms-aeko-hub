"""Verify auth microservice client behavior and error handling."""

import json

import pytest
import requests

LOGIN_PAYLOAD = {
    "email": "caio@example.com",
    "authenticated": True,
    "created": "2026-10-05T10:00:00.000Z",
    "expiration": "2026-10-05T11:00:00.000Z",
    "accessToken": "ms-access",
    "refreshToken": "ms-refresh",
}


class FakeResponse:
    """Stands in for `requests.Response`."""

    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text or json.dumps(payload if payload is not None else {})

    def json(self):
        """Return the scripted JSON response body."""
        if self._payload is None:
            raise ValueError("no JSON body")
        return self._payload


class RecordingRequest:
    """Captures every call `requests.request` would have made."""

    def __init__(self, response=None, error=None):
        self.response = (
            response if response is not None else FakeResponse(payload={"ok": True})
        )
        self.error = error
        self.calls = []

    def __call__(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        if self.error is not None:
            raise self.error
        return self.response


@pytest.fixture
def auth_env(monkeypatch):
    """Set test auth microservice environment variables."""
    monkeypatch.setenv("AUTH_MS_BASE_URL", "http://auth.test")
    monkeypatch.setenv("MS_HTTP_TIMEOUT", "60")


@pytest.fixture
def recorded_request(monkeypatch, auth_env):
    """Replace auth HTTP requests with a call recorder."""
    from cmd.api.integrations import auth_api, ms_auth_http

    request = RecordingRequest(FakeResponse(payload=LOGIN_PAYLOAD))
    monkeypatch.setattr(ms_auth_http.requests, "request", request)
    return request


def test_login_posts_email_and_password_only(recorded_request):
    """Verify that login posts email and password only."""
    from cmd.api.integrations import auth_api

    auth_api.login("caio@example.com", "secret")

    call = recorded_request.calls[0]
    assert call["method"] == "POST"
    assert call["url"] == "http://auth.test/api/auth/login"
    assert call["json"] == {"email": "caio@example.com", "password": "secret"}
    assert (
        "Authorization" not in call.get("headers")
        or "Authorization" not in call["headers"]
    )
    assert call["timeout"] == 60.0


def test_login_returns_the_ms_payload_as_is(recorded_request):
    """Verify that login returns the ms payload as is."""
    from cmd.api.integrations import auth_api

    assert auth_api.login("caio@example.com", "secret") == LOGIN_PAYLOAD


@pytest.mark.parametrize("env_var", ["AUTH_MS_BASE_URL", "MS_HTTP_TIMEOUT"])
def test_login_raises_naming_a_missing_env_var(monkeypatch, auth_env, env_var):
    """Verify that login raises naming a missing env var."""
    monkeypatch.delenv(env_var, raising=False)
    from cmd.api.integrations import auth_api

    with pytest.raises(RuntimeError) as error:
        auth_api.login("caio@example.com", "secret")
    assert env_var in str(error.value)


def test_login_raises_on_http_error(monkeypatch, auth_env):
    """Verify that login raises on http error."""
    from cmd.api.integrations import auth_api, ms_auth_http

    monkeypatch.setattr(
        ms_auth_http.requests,
        "request",
        RecordingRequest(FakeResponse(status_code=401, payload={"message": "denied"})),
    )
    with pytest.raises(auth_api.AuthError):
        auth_api.login("caio@example.com", "secret")


def test_login_raises_on_transport_error(monkeypatch, auth_env):
    """Verify that login raises on transport error."""
    from cmd.api.integrations import auth_api, ms_auth_http

    monkeypatch.setattr(
        ms_auth_http.requests,
        "request",
        RecordingRequest(error=requests.ConnectionError("down")),
    )
    with pytest.raises(auth_api.AuthError):
        auth_api.login("caio@example.com", "secret")
