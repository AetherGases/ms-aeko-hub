"""Expose discounted ROI and payback tools for investment analysis.

ROI posts the agent's JSON object to the calculator service. Payback is still
computed here: monthly cash flows discounted by monthly WACC over a fixed
60-month horizon, with payback as the first month covering CAPEX or -1.
"""

import json
import math
from typing import Any

from langchain_core.tools import Tool

from cmd.api.integrations import investment_api
from cmd.api.tools.constants import (
    ROI_HORIZON_MONTHS,
    ROI_PAYBACK_NOT_RECOVERED,
    ROI_DECIMAL_PLACES,
    ROI_MAX_WACC_MONTHLY,
    ROI_CASH_FLOW_FIELDS,
    ROI_REQUEST_FIELDS,
    ROI_REQUEST_DESCRIPTION,
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


def _number(value: object, field: str) -> int | float:
    """Validate a real numeric input, rejecting booleans and unsupported values."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f'"{field}" must be a number, got {value!r}.')

    if not math.isfinite(value):
        raise ValueError(f'"{field}" must be a number, got {value!r}.')

    return value


def _parse_capex(request: dict[str, Any]) -> int | float:
    """Validate that the initial investment is a positive real amount."""

    capex = _number(request.get("capex"), "capex")

    if capex <= 0:
        raise ValueError(
            f'"capex" must be the initial investment, above zero, got {capex!r}.'
        )

    return capex


def _parse_wacc(request: dict[str, Any]) -> int | float:
    """Validate that monthly WACC is at least zero and less than one."""

    wacc = _number(request.get("wacc_monthly"), "wacc_monthly")

    if not 0 <= wacc < ROI_MAX_WACC_MONTHLY:
        raise ValueError(
            f'"wacc_monthly" must be the monthly discount rate as a decimal '
            f"between 0 and {ROI_MAX_WACC_MONTHLY} (0.01 is 1% a month), got "
            f"{wacc!r}. An annual rate must be converted before it is sent."
        )

    return wacc


def _parse_cash_flows(request: dict[str, Any]) -> list[int | float]:
    """Normalize monthly cash flows to the fixed investment horizon."""

    given = [field for field in ROI_CASH_FLOW_FIELDS if field in request]

    if len(given) != 1:
        raise ValueError(
            f'The request must carry exactly one of "cash_flows" (the monthly '
            f'flows, up to {ROI_HORIZON_MONTHS}) or "monthly_cash_flow" (one '
            f"flow repeated over the {ROI_HORIZON_MONTHS} months), got "
            f"{' and '.join(given) if given else 'neither'}."
        )

    if given == ["monthly_cash_flow"]:
        flow = _number(request["monthly_cash_flow"], "monthly_cash_flow")
        return [flow] * ROI_HORIZON_MONTHS

    flows = request["cash_flows"]

    if not isinstance(flows, list) or flows == []:
        raise ValueError(
            f'"cash_flows" must be a list of monthly cash flows, oldest first, '
            f"got {flows!r}."
        )

    if len(flows) > ROI_HORIZON_MONTHS:
        raise ValueError(
            f'"cash_flows" must carry at most {ROI_HORIZON_MONTHS} monthly '
            f"flows, one per month of the horizon, got {len(flows)}."
        )

    flows = [_number(flow, f"cash_flows[{month}]") for month, flow in enumerate(flows)]

    return flows + [0] * (ROI_HORIZON_MONTHS - len(flows))


def _parse_request(request_input: str | dict[str, Any] | None) -> dict[str, Any]:
    """Validate investment fields and return CAPEX, monthly WACC, and cash flows."""

    request = _as_object(request_input)

    unknown = sorted(set(request) - set(ROI_REQUEST_FIELDS))
    if unknown != []:
        raise ValueError(
            f"The request takes no {', '.join(unknown)}. It accepts: "
            f"{', '.join(ROI_REQUEST_FIELDS)}."
        )

    return {
        "capex": _parse_capex(request),
        "wacc_monthly": _parse_wacc(request),
        "cash_flows": _parse_cash_flows(request),
    }


def _present_values(
    cash_flows: list[int | float], wacc_monthly: int | float
) -> list[int | float]:
    """Discount each monthly cash flow to its present value."""

    return [
        flow / (1 + wacc_monthly) ** month
        for month, flow in enumerate(cash_flows, start=1)
    ]


def _round(value: int | float) -> float:
    """Round a final financial result to the configured decimal precision."""

    return round(value, ROI_DECIMAL_PLACES)


def _payback_month(present_values: list[int | float], capex: int | float) -> int:
    """Return the first month covering CAPEX, or -1 if it is not recovered."""

    accumulated = 0.0

    for month, present_value in enumerate(present_values, start=1):
        accumulated += present_value

        if accumulated >= capex:
            return month

    return ROI_PAYBACK_NOT_RECOVERED


@logged(Module.TOOL, "calculate_roi")
def _calculate_roi(request_input: str | dict[str, Any] | None = "") -> dict[str, Any]:
    """Return the calculator service ROI payload for a JSON object string or dict."""

    decoded_object = _as_object(request_input)
    return investment_api.calculate_roi(decoded_object)


@logged(Module.TOOL, "calculate_payback")
def _calculate_payback(
    request_input: str | dict[str, Any] | None = "",
) -> dict[str, Any]:
    """Calculate discounted payback month, present value, and viability."""

    request = _parse_request(request_input)
    capex = request["capex"]

    present_values = _present_values(request["cash_flows"], request["wacc_monthly"])
    vp_total = sum(present_values)

    return {
        "capex": capex,
        "wacc_monthly": request["wacc_monthly"],
        "months": ROI_HORIZON_MONTHS,
        "vp_total": _round(vp_total),
        "payback_months": _payback_month(present_values, capex),
        "viable": capex <= vp_total,
    }


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
