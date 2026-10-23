"""Verify signed Cloudinary CDN uploads never return the signature payload."""

import pytest
import requests

from cmd.api.integrations import cloudinary_api
from tests.test_cloudinary_api import FakeResponse, RecordingRequest, SIGNATURE_PAYLOAD

SECURE_URL = "https://cloudinary/sadjasoda"


@pytest.fixture
def upload_env(monkeypatch):
    """Set the shared microservice HTTP timeout used by signed uploads."""
    monkeypatch.setenv("MS_HTTP_TIMEOUT", "60")


@pytest.fixture
def recorded_upload(monkeypatch, upload_env):
    """Replace Cloudinary CDN HTTP requests with a call recorder."""
    request = RecordingRequest(FakeResponse(payload={"secure_url": SECURE_URL}))
    monkeypatch.setattr(cloudinary_api.requests, "request", request)
    return request


def test_upload_signed_file_posts_to_the_cloudinary_cdn(recorded_upload):
    """Verify that upload signed file posts to the cloudinary cdn."""
    result = cloudinary_api.upload_signed_file(
        b"xlsx-bytes",
        "inventorio.xlsx",
        SIGNATURE_PAYLOAD,
    )

    call = recorded_upload.calls[0]
    assert result == SECURE_URL
    assert call["method"] == "POST"
    assert call["url"] == "https://api.cloudinary.com/v1_1/meu-cloud/image/upload"
    assert call["timeout"] == 60.0
    assert call["data"]["api_key"] == SIGNATURE_PAYLOAD["apiKey"]
    assert call["data"]["timestamp"] == SIGNATURE_PAYLOAD["timestamp"]
    assert call["data"]["signature"] == SIGNATURE_PAYLOAD["signature"]
    assert call["data"]["folder"] == SIGNATURE_PAYLOAD["cloudinaryFolder"]
    assert call["files"]["file"][0] == "inventorio.xlsx"
    headers = call.get("headers") or {}
    assert "Authorization" not in headers
    assert "authentication-key" not in headers


def test_upload_signed_file_returns_only_the_secure_url(recorded_upload):
    """Verify that upload signed file returns only the secure url."""
    result = cloudinary_api.upload_signed_file(
        b"xlsx-bytes",
        "inventorio.xlsx",
        SIGNATURE_PAYLOAD,
    )

    assert result == SECURE_URL
    assert result != SIGNATURE_PAYLOAD
    assert "signature" not in result
    assert "apiKey" not in result


def test_upload_signed_file_raises_cloudinary_error_on_http_error(
    monkeypatch, upload_env
):
    """Verify that upload signed file raises cloudinary error on http error."""
    monkeypatch.setattr(
        cloudinary_api.requests,
        "request",
        RecordingRequest(FakeResponse(status_code=400, payload={"message": "bad"})),
    )

    with pytest.raises(cloudinary_api.CloudinaryError):
        cloudinary_api.upload_signed_file(
            b"xlsx-bytes",
            "inventorio.xlsx",
            SIGNATURE_PAYLOAD,
        )


def test_upload_signed_file_raises_when_secure_url_is_missing(monkeypatch, upload_env):
    """Verify that upload signed file raises when secure url is missing."""
    monkeypatch.setattr(
        cloudinary_api.requests,
        "request",
        RecordingRequest(FakeResponse(payload={"url": "https://cloudinary/missing"})),
    )

    with pytest.raises(cloudinary_api.CloudinaryError):
        cloudinary_api.upload_signed_file(
            b"xlsx-bytes",
            "inventorio.xlsx",
            SIGNATURE_PAYLOAD,
        )


def test_upload_signed_file_raises_when_the_cdn_is_never_reached(
    monkeypatch, upload_env
):
    """Verify that upload signed file raises when the cdn is never reached."""
    monkeypatch.setattr(
        cloudinary_api.requests,
        "request",
        RecordingRequest(error=requests.ConnectionError("down")),
    )

    with pytest.raises(cloudinary_api.CloudinaryError):
        cloudinary_api.upload_signed_file(
            b"xlsx-bytes",
            "inventorio.xlsx",
            SIGNATURE_PAYLOAD,
        )
