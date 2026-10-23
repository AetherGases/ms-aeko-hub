"""Cloudinary microservice signatures and signed uploads to the Cloudinary CDN."""

import os
from typing import Any

import requests

from cmd.api.integrations.constants import (
    AUTHENTICATION_KEY_HEADER,
    CLOUDINARY_UPLOAD_SIGNATURE_PATH,
    INTERNAL_AUTHENTICATION_KEY_ENV,
)


class CloudinaryError(RuntimeError):
    """Raised when a call to Cloudinary or its microservice cannot be completed."""


def _base_url() -> str:
    """Resolve the Cloudinary microservice base URL from the environment."""

    base_url = os.environ.get("CLOUDINARY_MS_BASE_URL", "")

    if base_url == "":
        raise RuntimeError(
            "CLOUDINARY_MS_BASE_URL is not set. Please set it in the environment."
        )

    return base_url


def _timeout() -> float:
    """Resolve the shared HTTP timeout from the environment."""

    value = os.environ.get("MS_HTTP_TIMEOUT", "")

    if value == "":
        raise RuntimeError(
            "MS_HTTP_TIMEOUT is not set. Please set it in the environment."
        )

    return float(value)


def _internal_authentication_key() -> str:
    """Resolve the shared internal authentication-key header value."""

    value = os.environ.get(INTERNAL_AUTHENTICATION_KEY_ENV, "")

    if value == "":
        raise RuntimeError(
            f"{INTERNAL_AUTHENTICATION_KEY_ENV} is not set. Please set it in the environment."
        )

    return value


def _error_detail(response: Any) -> str:
    """Extract an API error message, falling back to the raw response text."""

    try:
        body = response.json()
    except ValueError:
        return response.text.strip()

    if not isinstance(body, dict):
        return response.text.strip()

    return (
        " - ".join(
            str(body[field]) for field in ("error_code", "message") if field in body
        )
        or response.text.strip()
    )


def _request(method: str, url: str, **kwargs: Any) -> Any:
    """Send a Cloudinary microservice HTTP request and translate transport and status errors."""

    headers = {AUTHENTICATION_KEY_HEADER: _internal_authentication_key()}

    try:
        response = requests.request(
            method, url, headers=headers, timeout=_timeout(), **kwargs
        )
    except requests.RequestException as exc:
        raise CloudinaryError(
            f"Could not reach the Cloudinary microservice at {url}: {exc}"
        ) from exc

    if response.status_code >= 400:
        raise CloudinaryError(
            f"The Cloudinary microservice answered {response.status_code} for {url}: "
            f"{_error_detail(response)}"
        )

    try:
        return response.json()
    except ValueError as exc:
        raise CloudinaryError(
            f"The Cloudinary microservice answered {response.status_code} for {url} with "
            f"something that is not JSON: {response.text.strip()!r}"
        ) from exc


def get_upload_signature(file_type: str) -> dict:
    """Return the Cloudinary upload signature for the file type using the internal key."""

    url = f"{_base_url()}{CLOUDINARY_UPLOAD_SIGNATURE_PATH}"
    return _request("GET", url, params={"fileType": file_type})


def upload_signed_file(
    file_bytes: bytes,
    file_name: str,
    signature_payload: dict,
) -> str:
    """Upload file bytes to Cloudinary and return only the secure URL."""

    cloud_name = signature_payload["cloudName"]
    resource_type = signature_payload["cloudinaryResourceType"]
    url = f"https://api.cloudinary.com/v1_1/{cloud_name}/{resource_type}/upload"
    data = {
        "api_key": signature_payload["apiKey"],
        "timestamp": signature_payload["timestamp"],
        "signature": signature_payload["signature"],
        "folder": signature_payload["cloudinaryFolder"],
    }
    files = {"file": (file_name, file_bytes)}

    try:
        response = requests.request(
            "POST",
            url,
            data=data,
            files=files,
            timeout=_timeout(),
        )
    except requests.RequestException as exc:
        raise CloudinaryError(f"Could not reach Cloudinary at {url}: {exc}") from exc

    if response.status_code >= 400:
        raise CloudinaryError(f"Cloudinary answered {response.status_code} for {url}.")

    try:
        payload: Any = response.json()
    except ValueError as exc:
        raise CloudinaryError(
            f"Cloudinary answered {response.status_code} for {url} with "
            f"something that is not JSON."
        ) from exc

    if not isinstance(payload, dict) or not payload.get("secure_url"):
        raise CloudinaryError("Cloudinary response did not include secure_url.")

    return payload["secure_url"]
