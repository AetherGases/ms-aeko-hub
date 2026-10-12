"""Verify internal authentication-key protection for POST /ai/report."""

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from internal.http.improvement_plan_handlers import (
    INTERNAL_AUTHENTICATION_KEY_ENV,
    require_inventory_report_authentication_key,
)


def test_require_inventory_report_authentication_key_accepts_a_matching_header(monkeypatch):
    """Verify that a matching authentication-key header passes validation."""
    monkeypatch.setenv(INTERNAL_AUTHENTICATION_KEY_ENV, "secret")
    require_inventory_report_authentication_key(authentication_key="secret")


def test_require_inventory_report_authentication_key_rejects_a_missing_header(monkeypatch):
    """Verify that a missing authentication-key header is rejected with 401."""
    monkeypatch.setenv(INTERNAL_AUTHENTICATION_KEY_ENV, "secret")
    with pytest.raises(HTTPException) as exc:
        require_inventory_report_authentication_key(authentication_key=None)
    assert exc.value.status_code == 401


def test_require_inventory_report_authentication_key_rejects_a_wrong_header(monkeypatch):
    """Verify that a wrong authentication-key header is rejected with 401."""
    monkeypatch.setenv(INTERNAL_AUTHENTICATION_KEY_ENV, "secret")
    with pytest.raises(HTTPException) as exc:
        require_inventory_report_authentication_key(authentication_key="other")
    assert exc.value.status_code == 401


def test_require_inventory_report_authentication_key_returns_503_when_unconfigured(monkeypatch):
    """Verify that missing server configuration yields 503."""
    monkeypatch.delenv(INTERNAL_AUTHENTICATION_KEY_ENV, raising=False)
    with pytest.raises(HTTPException) as exc:
        require_inventory_report_authentication_key(authentication_key="secret")
    assert exc.value.status_code == 503


def test_post_report_route_enforces_authentication_key_dependency(monkeypatch):
    """Verify that the dependency is wired on the report router."""
    from internal.http import improvement_plan_handlers

    monkeypatch.setenv(INTERNAL_AUTHENTICATION_KEY_ENV, "secret")
    app = FastAPI()
    app.include_router(improvement_plan_handlers.router)
    app.state.db = "fake-db"
    client = TestClient(app)

    assert client.post("/ai/report", json={}).status_code == 401
    assert client.post("/ai/report", json={}, headers={"authentication-key": "secret"}).status_code != 401
