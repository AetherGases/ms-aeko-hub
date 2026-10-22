"""Frozen HTTP client for the Cloudinary microservice upload-signature endpoint."""

import os
from typing import Any

import requests

from cmd.api.acl.open_ai.identity import current_ms_auth_access_token
from cmd.api.integrations.constants import CLOUDINARY_UPLOAD_SIGNATURE_PATH


class CloudinaryError(RuntimeError):
    """Raised when a call to the Cloudinary microservice cannot be completed."""


def _base_url() -> str:
    """Resolve the Cloudinary microservice base URL from the environment."""

    base_url = os.environ.get("CLOUDINARY_MS_BASE_URL", "")

    if base_url == "":
        raise RuntimeError(
            "CLOUDINARY_MS_BASE_URL is not set. Please set it in the environment."
        )

    return base_url


def _timeout() -> float:
    """Resolve the shared microservice HTTP timeout from the environment."""

    value = os.environ.get("MS_HTTP_TIMEOUT", "")

    if value == "":
        raise RuntimeError(
            "MS_HTTP_TIMEOUT is not set. Please set it in the environment."
        )

    return float(value)


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


def _request(method: str, url: str, api_key: str | None = None, **kwargs: Any) -> Any:
    """Send a Cloudinary microservice HTTP request and translate transport and status errors."""

    headers = {"Authorization": f"Bearer {current_ms_auth_access_token()}"}

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


def get_upload_signature(file_type: str, *, api_key: str | None = None) -> dict:
    """Return the Cloudinary upload signature for the file type as the bound ms-auth user."""

    url = f"{_base_url()}{CLOUDINARY_UPLOAD_SIGNATURE_PATH}"
    return _request("GET", url, api_key=api_key, params={"fileType": file_type})
