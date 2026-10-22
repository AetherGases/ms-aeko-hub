"""Signed uploads to the Cloudinary CDN using a microservice signature payload."""

import os
from typing import Any

import requests

from cmd.api.integrations.cloudinary_api import CloudinaryError


def _timeout() -> float:
    """Resolve the shared HTTP timeout from the environment."""

    value = os.environ.get("MS_HTTP_TIMEOUT", "")

    if value == "":
        raise RuntimeError(
            "MS_HTTP_TIMEOUT is not set. Please set it in the environment."
        )

    return float(value)


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
