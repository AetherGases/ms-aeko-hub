"""Calculator service client for discounted ROI over HTTP."""

import os
from typing import Any

import requests

from cmd.api.integrations.constants import (
    AUTHENTICATION_KEY_HEADER,
    INTERNAL_AUTHENTICATION_KEY_ENV,
    INVESTMENT_CALCULATOR_PAYBACK_PATH,
    INVESTMENT_CALCULATOR_ROI_PATH,
)


class InvestmentError(RuntimeError):
    """Raised when a call to the calculator service cannot be completed."""


def _base_url() -> str:
    """Resolve the calculator service base URL from the environment."""

    base_url = os.environ.get("INVESTMENT_MS_BASE_URL", "")

    if base_url == "":
        raise RuntimeError(
            "INVESTMENT_MS_BASE_URL is not set. Please set it in the environment."
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


def _request(method: str, url: str, **kwargs: Any) -> dict:
    """Send a calculator-service HTTP request and translate transport and status errors."""

    headers = {AUTHENTICATION_KEY_HEADER: _internal_authentication_key()}

    try:
        response = requests.request(
            method, url, headers=headers, timeout=_timeout(), **kwargs
        )
    except requests.RequestException as exc:
        raise InvestmentError(
            f"Could not reach the calculator service at {url}: {exc}"
        ) from exc

    try:
        body = response.json()
    except ValueError as exc:
        raise InvestmentError(
            f"The calculator service answered {response.status_code} for {url} with "
            f"something that is not JSON: {response.text.strip()!r}"
        ) from exc

    if not isinstance(body, dict):
        raise InvestmentError(
            f"The calculator service answered {response.status_code} for {url} with "
            f"a JSON value that is not an object."
        )

    if response.status_code >= 500:
        raise InvestmentError(
            f"The calculator service answered {response.status_code} for {url}."
        )

    if 400 <= response.status_code < 500:
        if body.get("error_code") == "validation_error":
            raise ValueError(body["message"])

        raise InvestmentError(
            f"The calculator service answered {response.status_code} for {url}."
        )

    return body


def calculate_roi(payload: dict) -> dict:
    """POST the investment payload to the calculator service and return its ROI answer."""

    url = f"{_base_url()}{INVESTMENT_CALCULATOR_ROI_PATH}"
    return _request("POST", url, json=payload)


def calculate_payback(payload: dict) -> dict:
    """POST the investment payload to the calculator service and return its payback answer."""

    url = f"{_base_url()}{INVESTMENT_CALCULATOR_PAYBACK_PATH}"
    return _request("POST", url, json=payload)
