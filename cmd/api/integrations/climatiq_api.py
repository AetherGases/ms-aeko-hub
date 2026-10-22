"""Expose Climatiq emission factor search and estimation as LangChain tools.

Requests use the versioned data API and a fixed data release. The agent selects
an activity factor from search results and supplies quantities for estimation.
"""

import json
import os
from typing import Any

import requests
from langchain_core.tools import Tool

from cmd.api.integrations.constants import (
    CLIMATIQ_BASE_URL,
    CLIMATIQ_DATA_VERSION,
    CLIMATIQ_ESTIMATE_DESCRIPTION,
    CLIMATIQ_ESTIMATE_FIELDS,
    CLIMATIQ_ESTIMATE_URL,
    CLIMATIQ_REQUEST_TIMEOUT,
    CLIMATIQ_RESULTS_PER_PAGE,
    CLIMATIQ_SEARCH_DESCRIPTION,
    CLIMATIQ_SEARCH_URL,
    CLIMATIQ_SELECTOR_FIELDS,
)
from internal.shared import Module, logged


class ClimatiqError(RuntimeError):
    """Raised when a call to the Climatiq API cannot be completed."""


def _api_key(api_key: str | None = None) -> str:
    """Resolve the Climatiq credential from the argument or environment and reject an empty key."""

    if api_key is None:
        api_key = os.environ.get("CLIMATIQ_API_KEY", "")

    if api_key == "":
        raise RuntimeError(
            "CLIMATIQ_API_KEY is not set. Please set it in the environment or pass it to _request()."
        )

    return api_key


def _error_detail(response: Any) -> str:
    """Extract an API error code and message, falling back to the raw response text."""

    try:
        body = response.json()
    except ValueError:
        return response.text.strip()

    return (
        " - ".join(
            str(body[field]) for field in ("error_code", "message") if field in body
        )
        or response.text.strip()
    )


def _request(method: str, url: str, api_key: str | None = None, **kwargs: Any) -> Any:
    """Send a Climatiq HTTP request and translate transport, status, and JSON errors."""

    headers = {"Authorization": f"Bearer {_api_key(api_key)}"}

    try:
        response = requests.request(
            method, url, headers=headers, timeout=CLIMATIQ_REQUEST_TIMEOUT, **kwargs
        )
    except requests.RequestException as exc:
        raise ClimatiqError(
            f"Could not reach the Climatiq API at {url}: {exc}"
        ) from exc

    if response.status_code >= 400:
        raise ClimatiqError(
            f"The Climatiq API answered {response.status_code} for {url}: "
            f"{_error_detail(response)}"
        )

    try:
        return response.json()
    except ValueError as exc:
        raise ClimatiqError(
            f"The Climatiq API answered {response.status_code} for {url} with "
            f"something that is not JSON: {response.text.strip()!r}"
        ) from exc


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


def _parse_search_query(query: str | None) -> str:
    """Validate and trim the nonempty activity or material search text."""

    if not isinstance(query, str) or query.strip() == "":
        raise ValueError(
            f"The query must be the activity or material to look up, got {query!r}."
        )

    return query.strip()


def _parse_estimate_request(
    request_input: str | dict[str, Any] | None,
) -> dict[str, Any]:
    """Validate estimate input and build the factor selector and activity payload."""

    request = _as_object(request_input)

    activity_id = request.get("activity_id")
    if not isinstance(activity_id, str) or activity_id.strip() == "":
        raise ValueError(
            f'"activity_id" must be an emission factor id from climatiq_search, '
            f"got {activity_id!r}."
        )

    parameters = request.get("parameters")
    if not isinstance(parameters, dict) or parameters == {}:
        raise ValueError(
            f'"parameters" must carry the quantity and its unit (for example '
            f'{{"weight": 100, "weight_unit": "t"}}), got {parameters!r}.'
        )

    known = {
        "activity_id",
        "parameters",
        *CLIMATIQ_SELECTOR_FIELDS,
        *CLIMATIQ_ESTIMATE_FIELDS,
    }
    unknown = sorted(set(request) - known)
    if unknown != []:
        accepted = ", ".join((*CLIMATIQ_SELECTOR_FIELDS, *CLIMATIQ_ESTIMATE_FIELDS))
        raise ValueError(
            f"The Climatiq estimate takes no {', '.join(unknown)}. Besides "
            f'"activity_id" and "parameters" it accepts: {accepted}.'
        )

    selector: dict[str, Any] = {
        "activity_id": activity_id.strip(),
        "data_version": CLIMATIQ_DATA_VERSION,
    }
    selector.update(
        {
            field: request[field]
            for field in CLIMATIQ_SELECTOR_FIELDS
            if field in request
        }
    )

    payload: dict[str, Any] = {"emission_factor": selector, "parameters": parameters}
    payload.update(
        {
            field: request[field]
            for field in CLIMATIQ_ESTIMATE_FIELDS
            if field in request
        }
    )

    return payload


@logged(Module.INTEGRATION, "climatiq_search")
def _climatiq_search(query: str | None = "") -> Any:
    """Search Climatiq for emission factors matching the supplied activity text."""

    return _request(
        "GET",
        CLIMATIQ_SEARCH_URL,
        params={
            "data_version": CLIMATIQ_DATA_VERSION,
            "query": _parse_search_query(query),
            "results_per_page": CLIMATIQ_RESULTS_PER_PAGE,
        },
    )


@logged(Module.INTEGRATION, "climatiq_estimate")
def _climatiq_estimate(request_input: str | dict[str, Any] | None = "") -> Any:
    """Estimate emissions using the selected factor and supplied activity quantities."""

    return _request(
        "POST", CLIMATIQ_ESTIMATE_URL, json=_parse_estimate_request(request_input)
    )


def get_climatiq_tools() -> list[Tool]:
    """Return emission factor search and estimation tools in workflow order."""

    return [
        Tool(
            name="climatiq_search",
            description=CLIMATIQ_SEARCH_DESCRIPTION,
            func=_climatiq_search,
        ),
        Tool(
            name="climatiq_estimate",
            description=CLIMATIQ_ESTIMATE_DESCRIPTION,
            func=_climatiq_estimate,
        ),
    ]
