"""Verify cloudinary microservice client behavior and error handling."""

import ast
import json
from pathlib import Path

import pytest
import requests

from cmd.api.acl.open_ai.identity import (
    bind_ms_auth_access_token,
    reset_ms_auth_access_token,
)
from cmd.api.integrations import cloudinary_api
from cmd.api.integrations.constants import INTERNAL_AUTHENTICATION_KEY_ENV


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


SIGNATURE_PAYLOAD = {
    "signature": "a1b2c3d4e5f6",
    "timestamp": 1728067200,
    "apiKey": "123456789012345",
    "cloudName": "meu-cloud",
    "cloudinaryFolder": "uploads",
    "cloudinaryResourceType": "image",
}


@pytest.fixture(autouse=True)
def bound_ms_auth_token():
    """Bind a user token so Cloudinary calls can prove they ignore it."""
    token = bind_ms_auth_access_token("ms-user-token")
    yield "ms-user-token"
    reset_ms_auth_access_token(token)


@pytest.fixture
def cloudinary_env(monkeypatch):
    """Set test Cloudinary microservice environment variables."""
    monkeypatch.setenv("CLOUDINARY_MS_BASE_URL", "http://cloudinary.test")
    monkeypatch.setenv(INTERNAL_AUTHENTICATION_KEY_ENV, "internal-token")
    monkeypatch.setenv("MS_HTTP_TIMEOUT", "60")


@pytest.fixture
def recorded_request(monkeypatch, cloudinary_env):
    """Replace Cloudinary HTTP requests with a call recorder."""
    request = RecordingRequest(FakeResponse(payload=SIGNATURE_PAYLOAD))
    monkeypatch.setattr(cloudinary_api.requests, "request", request)
    return request


def test_get_upload_signature_gets_the_upload_signature_endpoint(recorded_request):
    """Verify that get upload signature gets the upload signature endpoint."""
    cloudinary_api.get_upload_signature("XLSX")

    call = recorded_request.calls[0]
    assert call["method"] == "GET"
    assert call["url"] == "http://cloudinary.test/api/cloudinary/upload-signature"
    assert call["params"] == {"fileType": "XLSX"}


def test_get_upload_signature_authenticates_with_the_internal_authentication_key(
    recorded_request,
):
    """Verify that get upload signature sends the internal authentication-key header."""
    cloudinary_api.get_upload_signature("XLSX")

    headers = recorded_request.calls[0]["headers"]
    assert headers["authentication-key"] == "internal-token"
    assert "Authorization" not in headers


def test_get_upload_signature_never_waits_forever(recorded_request):
    """Verify that get upload signature never waits forever."""
    cloudinary_api.get_upload_signature("XLSX")

    assert recorded_request.calls[0]["timeout"] == 60.0


def test_get_upload_signature_returns_the_ms_payload_as_is(recorded_request):
    """Verify that get upload signature returns the ms payload as is."""
    assert cloudinary_api.get_upload_signature("XLSX") == SIGNATURE_PAYLOAD


def test_get_upload_signature_ignores_the_bound_user_bearer(
    recorded_request, bound_ms_auth_token
):
    """Verify that get upload signature does not send the signed-in user's Bearer."""
    cloudinary_api.get_upload_signature("IMAGE")

    headers = recorded_request.calls[0]["headers"]
    assert headers["authentication-key"] == "internal-token"
    assert headers.get("Authorization") != f"Bearer {bound_ms_auth_token}"


@pytest.mark.parametrize(
    "env_var",
    ["CLOUDINARY_MS_BASE_URL", "MS_HTTP_TIMEOUT", INTERNAL_AUTHENTICATION_KEY_ENV],
)
def test_get_upload_signature_raises_naming_a_missing_env_var(
    monkeypatch, cloudinary_env, env_var
):
    """Verify that get upload signature raises naming a missing env var."""
    monkeypatch.delenv(env_var, raising=False)

    with pytest.raises(RuntimeError) as error:
        cloudinary_api.get_upload_signature("XLSX")

    assert env_var in str(error.value)


def test_get_upload_signature_raises_on_http_error(monkeypatch, cloudinary_env):
    """Verify that get upload signature raises on http error."""
    monkeypatch.setattr(
        cloudinary_api.requests,
        "request",
        RecordingRequest(FakeResponse(400, {"message": "bad file type"})),
    )

    with pytest.raises(cloudinary_api.CloudinaryError) as error:
        cloudinary_api.get_upload_signature("XLSX")

    assert "400" in str(error.value)


@pytest.mark.parametrize("payload", [["message"], "message"])
def test_get_upload_signature_raises_cloudinary_error_on_non_object_json_error_body(
    monkeypatch, cloudinary_env, payload
):
    """Verify that a non-object JSON error body still raises CloudinaryError."""
    monkeypatch.setattr(
        cloudinary_api.requests,
        "request",
        RecordingRequest(FakeResponse(400, payload)),
    )

    with pytest.raises(cloudinary_api.CloudinaryError) as error:
        cloudinary_api.get_upload_signature("XLSX")

    assert "400" in str(error.value)


def test_get_upload_signature_raises_when_the_service_is_never_reached(
    monkeypatch, cloudinary_env
):
    """Verify that get upload signature raises when the service is never reached."""
    monkeypatch.setattr(
        cloudinary_api.requests,
        "request",
        RecordingRequest(error=requests.ConnectionError("name resolution failed")),
    )

    with pytest.raises(cloudinary_api.CloudinaryError) as error:
        cloudinary_api.get_upload_signature("XLSX")

    assert "name resolution failed" in str(error.value)


def test_get_upload_signature_raises_when_a_successful_answer_is_not_json(
    monkeypatch, cloudinary_env
):
    """Verify that get upload signature raises when a successful answer is not json."""
    monkeypatch.setattr(
        cloudinary_api.requests,
        "request",
        RecordingRequest(FakeResponse(200, None, text="not json")),
    )

    with pytest.raises(cloudinary_api.CloudinaryError):
        cloudinary_api.get_upload_signature("XLSX")


def test_cloudinary_api_imports_internal_key_from_integrations_constants():
    """Keep the outbound Cloudinary client on integrations constants."""
    tree = ast.parse(Path(cloudinary_api.__file__).read_text(encoding="utf-8"))
    sources = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and node.module
        and any(alias.name == "INTERNAL_AUTHENTICATION_KEY_ENV" for alias in node.names)
    }
    assert sources == {"cmd.api.integrations.constants"}
