"""Expose discounted ROI and payback tools for investment analysis.

Both tools POST the agent's JSON object to the calculator service.
"""

import json
from typing import Any

from langchain_core.tools import Tool

from cmd.api.integrations import investment_api
from cmd.api.tools.constants import (
    ROI_DESCRIPTION,
    PAYBACK_DESCRIPTION,
)
from internal.shared import Module, logged


def _as_object(request_input: str | dict[str, Any] | None) -> dict[str, Any]:
    """Accept a dictionary or decode a JSON object string, rejecting other input."""

    if isinstance(request_input, dict):
        return request_input

    if not isinstance(request_input, str) or request_input.strip() == "":
        raise ValueError(
            f"The request must be a JSON object string, got {request_input!r}."
        )

    try:
        parsed = json.loads(request_input)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"The request must be a JSON object string, got {request_input!r}."
        ) from exc

    if not isinstance(parsed, dict):
        raise ValueError(
            f"The request must be a JSON object string, got {request_input!r}."
        )

    return parsed


@logged(Module.TOOL, "calculate_roi")
def _calculate_roi(request_input: str | dict[str, Any] | None = "") -> dict[str, Any]:
    """Return the calculator service ROI payload for a JSON object string or dict."""

    decoded_object = _as_object(request_input)
    return investment_api.calculate_roi(decoded_object)


@logged(Module.TOOL, "calculate_payback")
def _calculate_payback(
    request_input: str | dict[str, Any] | None = "",
) -> dict[str, Any]:
    """Return the calculator service payback payload for a JSON object string or dict."""

    decoded_object = _as_object(request_input)
    return investment_api.calculate_payback(decoded_object)


def get_roi_payback_tools() -> list[Tool]:
    """Return discounted ROI and payback tools for investment analysis."""

    return [
        Tool(
            name="calculate_roi",
            description=ROI_DESCRIPTION,
            func=_calculate_roi,
        ),
        Tool(
            name="calculate_payback",
            description=PAYBACK_DESCRIPTION,
            func=_calculate_payback,
        ),
    ]
