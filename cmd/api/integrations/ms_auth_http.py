"""Shared HTTP helpers for auth microservice integration clients."""

import os
from typing import Any, Type

import requests


def base_url() -> str:
    """Resolve the auth microservice base URL from the environment."""
    base_url = os.environ.get("AUTH_MS_BASE_URL", "")
    if base_url == "":
        raise RuntimeError(
            "AUTH_MS_BASE_URL is not set. Please set it in the environment."
        )
    return base_url


def http_timeout() -> float:
    """Resolve the shared microservice HTTP timeout from the environment."""
    value = os.environ.get("MS_HTTP_TIMEOUT", "")
    if value == "":
        raise RuntimeError(
            "MS_HTTP_TIMEOUT is not set. Please set it in the environment."
        )
    return float(value)


def error_detail(response: Any) -> str:
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


def request_json(
    method: str,
    url: str,
    *,
    error_type: Type[RuntimeError],
    headers: dict[str, str] | None = None,
    **kwargs: Any,
) -> Any:
    """Send an ms-auth HTTP request and translate transport and status errors."""
    try:
        response = requests.request(
            method,
            url,
            headers=headers or {},
            timeout=http_timeout(),
            **kwargs,
        )
    except requests.RequestException as exc:
        raise error_type(
            f"Could not reach the auth microservice at {url}: {exc}"
        ) from exc

    if response.status_code >= 400:
        raise error_type(
            f"The auth microservice answered {response.status_code} for {url}: "
            f"{error_detail(response)}"
        )

    try:
        return response.json()
    except ValueError as exc:
        raise error_type(
            f"The auth microservice answered {response.status_code} for {url} with "
            f"something that is not JSON: {response.text.strip()!r}"
        ) from exc
