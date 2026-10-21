"""Verify ms-auth Bearer resolution through the profile endpoint."""

import asyncio
import hashlib
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cmd.api.acl.ms_auth_security import (
    MsAuthPrincipal,
    parse_bearer_authorization,
    resolve_ms_auth_access_token,
    resolve_ms_auth_access_token_cached,
)
from cmd.api.integrations.profile_api import ProfileError
from internal.http.ms_auth_dependencies import MsAuth
from tests.conftest import FakeRedis
from tests.test_profile_api import PROFILE_PAYLOAD


def _profile_cache_key(access_token: str) -> str:
    """Return the Redis key used to cache a resolved ms-auth principal."""
    digest = hashlib.sha256(access_token.encode("utf-8")).hexdigest()
    return f"msauth:profile:{digest}"


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


def test_cached_resolve_stores_the_principal_in_redis(monkeypatch):
    """Verify that a profile cache hit is served from Redis, not process memory."""
    redis = FakeRedis()
    calls = []

    def get_profile(token):
        """Record each live ms-auth profile lookup."""
        calls.append(token)
        return PROFILE_PAYLOAD

    monkeypatch.setattr("cmd.api.acl.ms_auth_security.get_profile", get_profile)

    first = resolve_ms_auth_access_token_cached("ms-access", redis)
    other = FakeRedis()
    resolve_ms_auth_access_token_cached("ms-access", other)
    second = resolve_ms_auth_access_token_cached("ms-access", redis)

    assert calls == ["ms-access", "ms-access"]
    assert first == second == MsAuthPrincipal("ms-access", 1, 90, PROFILE_PAYLOAD)
    key = _profile_cache_key("ms-access")
    assert key in redis.values
    assert redis.expirations[key] == 30
    stored = json.loads(redis.values[key])
    assert stored["id_external_user"] == 1
    assert stored["id_external_company"] == 90
    assert stored["profile"] == PROFILE_PAYLOAD
    assert "access_token" not in stored


def test_cached_resolve_without_redis_always_hits_ms_auth(monkeypatch):
    """Verify that missing Redis does not fall back to an in-process profile cache."""
    calls = []

    def get_profile(token):
        """Record each live ms-auth profile lookup."""
        calls.append(token)
        return PROFILE_PAYLOAD

    monkeypatch.setattr("cmd.api.acl.ms_auth_security.get_profile", get_profile)

    resolve_ms_auth_access_token_cached("ms-access")
    resolve_ms_auth_access_token_cached("ms-access", None)

    assert calls == ["ms-access", "ms-access"]


def test_require_ms_auth_principal_reuses_the_redis_profile_cache(monkeypatch):
    """Verify that HTTP ms-auth resolution shares the Redis profile cache."""
    redis = FakeRedis()
    calls = []

    def get_profile(token):
        """Record each live ms-auth profile lookup."""
        calls.append(token)
        return PROFILE_PAYLOAD

    monkeypatch.setattr("cmd.api.acl.ms_auth_security.get_profile", get_profile)

    app = FastAPI()
    app.state.redis = redis

    @app.get("/protected")
    def protected(principal: MsAuth):
        """Return the bound user id so the test can see a successful resolve."""
        return {"id_external_user": principal.id_external_user}

    client = TestClient(app)
    headers = {"Authorization": "Bearer ms-access"}
    assert client.get("/protected", headers=headers).status_code == 200
    assert client.get("/protected", headers=headers).status_code == 200
    assert calls == ["ms-access"]
