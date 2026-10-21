"""Verify ms-auth Bearer resolution through the profile endpoint."""

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cmd.api.acl.ms_auth_security import (
    MsAuthPrincipal,
    parse_bearer_authorization,
    resolve_ms_auth_access_token,
)
from cmd.api.integrations.profile_api import ProfileError
from internal.http.ms_auth_dependencies import MsAuth
from tests.test_profile_api import PROFILE_PAYLOAD


def _protected_client():
    """Build a TestClient whose only route requires a valid ms-auth principal."""
    app = FastAPI()

    @app.get("/protected")
    def protected(principal: MsAuth):
        """Return the bound user id so the test can see a successful resolve."""
        return {"id_external_user": principal.id_external_user}

    return TestClient(app)


def test_parse_bearer_authorization_reads_the_token():
    """Verify that parse bearer authorization reads the token."""
    assert parse_bearer_authorization("Bearer ms-access") == "ms-access"
    assert parse_bearer_authorization("bearer ms-access") == "ms-access"
    assert parse_bearer_authorization(None) is None
    assert parse_bearer_authorization("Basic abc") is None


def test_resolve_ms_auth_access_token_returns_principal(monkeypatch):
    """Verify that resolve ms auth access token returns principal."""
    monkeypatch.setattr(
        "cmd.api.acl.ms_auth_security.get_profile",
        lambda token: PROFILE_PAYLOAD,
    )

    principal = resolve_ms_auth_access_token("ms-access")

    assert principal == MsAuthPrincipal("ms-access", 1, 90, PROFILE_PAYLOAD)


def test_resolve_ms_auth_access_token_rejects_profile_errors(monkeypatch):
    """Verify that resolve ms auth access token rejects profile errors."""

    def fail(_token):
        """Raise a profile error for invalid tokens."""
        raise ProfileError("denied")

    monkeypatch.setattr("cmd.api.acl.ms_auth_security.get_profile", fail)

    with pytest.raises(ValueError, match="Invalid or expired access token."):
        resolve_ms_auth_access_token("ms-access")


def test_require_ms_auth_principal_rejects_an_invalid_token(monkeypatch):
    """Verify that an invalid ms-auth token still returns 401."""

    def fail(_token):
        """Raise a profile error for invalid tokens."""
        raise ProfileError("denied")

    monkeypatch.setattr("cmd.api.acl.ms_auth_security.get_profile", fail)

    response = _protected_client().get(
        "/protected",
        headers={"Authorization": "Bearer bad-token"},
    )

    assert response.status_code == 401
    assert "bad-token" not in response.text


def test_require_ms_auth_principal_resolves_off_the_event_loop(monkeypatch):
    """Verify that require ms auth principal does not call get_profile on the event loop."""
    seen = []

    def get_profile(_token):
        """Record whether the blocking profile lookup ran on the event loop."""
        try:
            asyncio.get_running_loop()
            seen.append(True)
        except RuntimeError:
            seen.append(False)
        return PROFILE_PAYLOAD

    monkeypatch.setattr("cmd.api.acl.ms_auth_security.get_profile", get_profile)

    response = _protected_client().get(
        "/protected",
        headers={"Authorization": "Bearer loop-token"},
    )

    assert response.status_code == 200
    assert seen == [False]
