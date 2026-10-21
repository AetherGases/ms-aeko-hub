"""Frozen HTTP client for the Inventory microservice create-inventory endpoint."""

import os
from typing import Any

import requests

from cmd.api.acl.open_ai.identity import current_ms_auth_access_token

INVENTORY_CREATE_PATH = "/api/inventories"


class InventoryError(RuntimeError):
    """Raised when a call to the Inventory microservice cannot be completed."""


def _base_url() -> str:
    """Resolve the Inventory microservice base URL from the environment."""

    base_url = os.environ.get("INVENTORY_MS_BASE_URL", "")

    if base_url == "":
        raise RuntimeError(
            "INVENTORY_MS_BASE_URL is not set. Please set it in the environment."
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

    return " - ".join(
        str(body[field]) for field in ("error_code", "message") if field in body
    ) or response.text.strip()


def _request(method: str, url: str, api_key: str | None = None, **kwargs: Any) -> Any:
    """Send an Inventory microservice HTTP request and translate transport and status errors."""

    headers = {"Authorization": f"Bearer {current_ms_auth_access_token()}"}

    try:
        response = requests.request(
            method, url, headers=headers, timeout=_timeout(), **kwargs
        )
    except requests.RequestException as exc:
        raise InventoryError(
            f"Could not reach the Inventory microservice at {url}: {exc}"
        ) from exc

    if response.status_code >= 400:
        raise InventoryError(
            f"The Inventory microservice answered {response.status_code} for {url}: "
            f"{_error_detail(response)}"
        )

    try:
        return response.json()
    except ValueError as exc:
        raise InventoryError(
            f"The Inventory microservice answered {response.status_code} for {url} with "
            f"something that is not JSON: {response.text.strip()!r}"
        ) from exc


def create_inventory(
    name: str, file_name: str, path: str, *, api_key: str | None = None
) -> dict:
    """Create an inventory record as the bound ms-auth user and return the payload as-is."""

    url = f"{_base_url()}{INVENTORY_CREATE_PATH}"
    return _request(
        "POST",
        url,
        api_key=api_key,
        json={"name": name, "fileName": file_name, "path": path},
    )
