"""Verify inventory microservice client behavior and error handling."""

import json

import pytest
import requests

from cmd.api.acl.open_ai.identity import (
    bind_ms_auth_access_token,
    reset_ms_auth_access_token,
)
from cmd.api.integrations import inventory_api


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


INVENTORY_PAYLOAD = {
    "id": 1,
    "name": "relatório",
    "type": "INPUT",
    "status": "PROCESSING",
    "createdAt": "2026-10-04T19:30:00",
    "storageFile": {
        "id": 10,
        "fileName": "inventorio-principal.xlsx",
        "path": "https://cloudinary/sadjasoda",
        "createdAt": "2026-10-04T19:30:00",
    },
}


@pytest.fixture(autouse=True)
def bound_ms_auth_token():
    """Bind the signed-in user's ms-auth access token for Inventory calls."""
    token = bind_ms_auth_access_token("ms-user-token")
    yield "ms-user-token"
    reset_ms_auth_access_token(token)


@pytest.fixture
def inventory_env(monkeypatch):
    """Set test Inventory microservice environment variables."""
    monkeypatch.setenv("INVENTORY_MS_BASE_URL", "http://inventory.test")
    monkeypatch.setenv("INVENTORY_MS_API_KEY", "inv-key")
    monkeypatch.setenv("MS_HTTP_TIMEOUT", "60")


@pytest.fixture
def recorded_request(monkeypatch, inventory_env):
    """Replace Inventory HTTP requests with a call recorder."""
    request = RecordingRequest(FakeResponse(payload=INVENTORY_PAYLOAD))
    monkeypatch.setattr(inventory_api.requests, "request", request)
    return request


def test_create_inventory_posts_to_the_inventories_endpoint(recorded_request):
    """Verify that create inventory posts to the inventories endpoint."""
    inventory_api.create_inventory(
        "relatório", "inventorio-principal.xlsx", "https://cloudinary/sadjasoda"
    )

    call = recorded_request.calls[0]
    assert call["method"] == "POST"
    assert call["url"] == "http://inventory.test/api/inventories"
    assert call["json"] == {
        "name": "relatório",
        "fileName": "inventorio-principal.xlsx",
        "path": "https://cloudinary/sadjasoda",
    }


def test_create_inventory_authenticates_with_a_bearer_token(recorded_request):
    """Verify that create inventory authenticates with the bound user Bearer."""
    inventory_api.create_inventory(
        "relatório", "inventorio-principal.xlsx", "https://cloudinary/sadjasoda"
    )

    assert (
        recorded_request.calls[0]["headers"]["Authorization"] == "Bearer ms-user-token"
    )
    assert recorded_request.calls[0]["headers"]["Authorization"] != "Bearer inv-key"


def test_create_inventory_never_waits_forever(recorded_request):
    """Verify that create inventory never waits forever."""
    inventory_api.create_inventory(
        "relatório", "inventorio-principal.xlsx", "https://cloudinary/sadjasoda"
    )

    assert recorded_request.calls[0]["timeout"] == 60.0


def test_create_inventory_returns_the_ms_payload_as_is(recorded_request):
    """Verify that create inventory returns the ms payload as is."""
    result = inventory_api.create_inventory(
        "relatório", "inventorio-principal.xlsx", "https://cloudinary/sadjasoda"
    )

    assert result == INVENTORY_PAYLOAD
    assert result["storageFile"]["path"] == "https://cloudinary/sadjasoda"


@pytest.mark.parametrize(
    "env_var",
    ["INVENTORY_MS_BASE_URL", "MS_HTTP_TIMEOUT"],
)
def test_create_inventory_raises_naming_a_missing_env_var(
    monkeypatch, inventory_env, env_var
):
    """Verify that create inventory raises naming a missing env var."""
    monkeypatch.delenv(env_var, raising=False)

    with pytest.raises(RuntimeError) as error:
        inventory_api.create_inventory(
            "relatório", "inventorio-principal.xlsx", "https://cloudinary/sadjasoda"
        )

    assert env_var in str(error.value)


def test_create_inventory_raises_on_http_error(monkeypatch, inventory_env):
    """Verify that create inventory raises on http error."""
    monkeypatch.setattr(
        inventory_api.requests,
        "request",
        RecordingRequest(FakeResponse(500, {"message": "internal error"})),
    )

    with pytest.raises(inventory_api.InventoryError) as error:
        inventory_api.create_inventory(
            "relatório", "inventorio-principal.xlsx", "https://cloudinary/sadjasoda"
        )

    assert "500" in str(error.value)


@pytest.mark.parametrize("payload", [["message"], "message"])
def test_create_inventory_raises_inventory_error_on_non_object_json_error_body(
    monkeypatch, inventory_env, payload
):
    """Verify that a non-object JSON error body still raises InventoryError."""
    monkeypatch.setattr(
        inventory_api.requests,
        "request",
        RecordingRequest(FakeResponse(500, payload)),
    )

    with pytest.raises(inventory_api.InventoryError) as error:
        inventory_api.create_inventory(
            "relatório", "inventorio-principal.xlsx", "https://cloudinary/sadjasoda"
        )

    assert "500" in str(error.value)


def test_create_inventory_raises_when_the_service_is_never_reached(
    monkeypatch, inventory_env
):
    """Verify that create inventory raises when the service is never reached."""
    monkeypatch.setattr(
        inventory_api.requests,
        "request",
        RecordingRequest(error=requests.ConnectionError("name resolution failed")),
    )

    with pytest.raises(inventory_api.InventoryError) as error:
        inventory_api.create_inventory(
            "relatório", "inventorio-principal.xlsx", "https://cloudinary/sadjasoda"
        )

    assert "name resolution failed" in str(error.value)


def test_create_inventory_raises_when_a_successful_answer_is_not_json(
    monkeypatch, inventory_env
):
    """Verify that create inventory raises when a successful answer is not json."""
    monkeypatch.setattr(
        inventory_api.requests,
        "request",
        RecordingRequest(FakeResponse(200, None, text="not json")),
    )

    with pytest.raises(inventory_api.InventoryError):
        inventory_api.create_inventory(
            "relatório", "inventorio-principal.xlsx", "https://cloudinary/sadjasoda"
        )
