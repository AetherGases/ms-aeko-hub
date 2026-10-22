"""Verify climatiq api behavior and error handling."""

import json

import pytest
import requests
from langchain_core.tools import Tool

from cmd.api.integrations import climatiq_api


class FakeResponse:
    """Stands in for `requests.Response`."""

    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text or json.dumps(payload if payload is not None else {})

    def json(self):
        """Return the scripted JSON response body."""
        if self._payload is None:
            raise ValueError("no JSON body")
        return self._payload


class RecordingRequest:
    """Captures every call `requests.request` would have made."""

    def __init__(self, response=None, error=None):
        self.response = (
            response if response is not None else FakeResponse(payload={"ok": True})
        )
        self.error = error
        self.calls = []

    def __call__(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        if self.error is not None:
            raise self.error
        return self.response


@pytest.fixture
def api_key_env(monkeypatch):
    """Set a test Climatiq API key."""
    monkeypatch.setenv("CLIMATIQ_API_KEY", "key-from-env")


@pytest.fixture
def recorded_request(monkeypatch, api_key_env):
    """Replace Climatiq HTTP requests with a call recorder."""
    request = RecordingRequest()
    monkeypatch.setattr(climatiq_api.requests, "request", request)
    return request


def test_api_key_falls_back_to_the_environment(api_key_env):
    """Verify that api key falls back to the environment."""
    assert climatiq_api._api_key() == "key-from-env"


def test_api_key_prefers_the_value_it_is_given(api_key_env):
    """Verify that api key prefers the value it is given."""
    assert climatiq_api._api_key("explicit-key") == "explicit-key"


@pytest.mark.parametrize("value", ["", None])
def test_api_key_raises_naming_the_missing_variable(monkeypatch, value):
    """Verify that api key raises naming the missing variable."""
    monkeypatch.delenv("CLIMATIQ_API_KEY", raising=False)

    with pytest.raises(RuntimeError) as error:
        climatiq_api._api_key(value)

    assert "CLIMATIQ_API_KEY" in str(error.value)


def test_request_sends_query_parameters_on_a_get(recorded_request):
    """Verify that request sends query parameters on a get."""
    climatiq_api._request(
        "GET", climatiq_api.CLIMATIQ_SEARCH_URL, params={"query": "cement"}
    )

    call = recorded_request.calls[0]
    assert call["method"] == "GET"
    assert call["url"] == climatiq_api.CLIMATIQ_SEARCH_URL
    assert call["params"] == {"query": "cement"}


def test_request_sends_a_json_body_on_a_post(recorded_request):
    """Verify that request sends a json body on a post."""
    climatiq_api._request(
        "POST", climatiq_api.CLIMATIQ_ESTIMATE_URL, json={"parameters": {}}
    )

    call = recorded_request.calls[0]
    assert call["method"] == "POST"
    assert call["json"] == {"parameters": {}}


def test_request_authenticates_with_a_bearer_token(recorded_request):
    """Verify that request authenticates with a bearer token."""
    climatiq_api._request("GET", climatiq_api.CLIMATIQ_SEARCH_URL)

    assert (
        recorded_request.calls[0]["headers"]["Authorization"] == "Bearer key-from-env"
    )


def test_request_never_waits_forever(recorded_request):
    """Verify that request never waits forever."""
    climatiq_api._request("GET", climatiq_api.CLIMATIQ_SEARCH_URL)

    assert recorded_request.calls[0]["timeout"] == climatiq_api.CLIMATIQ_REQUEST_TIMEOUT


def test_request_returns_the_parsed_body(monkeypatch, api_key_env):
    """Verify that request returns the parsed body."""
    monkeypatch.setattr(
        climatiq_api.requests,
        "request",
        RecordingRequest(FakeResponse(payload={"co2e": 12.5})),
    )

    assert climatiq_api._request("POST", climatiq_api.CLIMATIQ_ESTIMATE_URL) == {
        "co2e": 12.5
    }


def test_request_raises_carrying_what_the_api_said_about_a_rejected_request(
    monkeypatch, api_key_env
):
    """Verify that request raises carrying what the api said about a rejected request."""
    body = {
        "error": "bad_request",
        "error_code": "no_matching_resource_found",
        "message": "No emission factor matched the given activity id.",
    }
    monkeypatch.setattr(
        climatiq_api.requests, "request", RecordingRequest(FakeResponse(400, body))
    )

    with pytest.raises(climatiq_api.ClimatiqError) as error:
        climatiq_api._request("POST", climatiq_api.CLIMATIQ_ESTIMATE_URL)

    message = str(error.value)
    assert "400" in message
    assert "no_matching_resource_found" in message
    assert "No emission factor matched the given activity id." in message


def test_request_raises_on_an_error_body_that_is_not_json(monkeypatch, api_key_env):
    """Verify that request raises on an error body that is not json."""
    monkeypatch.setattr(
        climatiq_api.requests,
        "request",
        RecordingRequest(FakeResponse(502, None, text="<html>Bad Gateway</html>")),
    )

    with pytest.raises(climatiq_api.ClimatiqError) as error:
        climatiq_api._request("GET", climatiq_api.CLIMATIQ_SEARCH_URL)

    assert "502" in str(error.value)


def test_request_raises_when_climatiq_is_never_reached(monkeypatch, api_key_env):
    """Verify that request raises when climatiq is never reached."""
    monkeypatch.setattr(
        climatiq_api.requests,
        "request",
        RecordingRequest(error=requests.ConnectionError("name resolution failed")),
    )

    with pytest.raises(climatiq_api.ClimatiqError) as error:
        climatiq_api._request("GET", climatiq_api.CLIMATIQ_SEARCH_URL)

    assert "name resolution failed" in str(error.value)


def test_request_raises_when_a_successful_answer_is_not_json(monkeypatch, api_key_env):
    """Verify that request raises when a successful answer is not json."""
    monkeypatch.setattr(
        climatiq_api.requests,
        "request",
        RecordingRequest(FakeResponse(200, None, text="not json")),
    )

    with pytest.raises(climatiq_api.ClimatiqError):
        climatiq_api._request("GET", climatiq_api.CLIMATIQ_SEARCH_URL)


def test_parse_search_query_drops_surrounding_whitespace():
    """Verify that parse search query drops surrounding whitespace."""
    assert climatiq_api._parse_search_query("  portland cement  ") == "portland cement"


@pytest.mark.parametrize("query", ["", "   ", None, 42, ["cement"]])
def test_parse_search_query_rejects_anything_that_is_not_search_text(query):
    """Verify that parse search query rejects anything that is not search text."""
    with pytest.raises(ValueError) as error:
        climatiq_api._parse_search_query(query)

    assert repr(query) in str(error.value)


def test_parse_estimate_request_accepts_a_json_object_string():
    """Verify that parse estimate request accepts a json object string."""
    parsed = climatiq_api._parse_estimate_request(
        '{"activity_id": "metals-type_basic_iron_and_steel",'
        ' "parameters": {"weight": 100, "weight_unit": "t"}}'
    )

    assert (
        parsed["emission_factor"]["activity_id"] == "metals-type_basic_iron_and_steel"
    )
    assert parsed["parameters"] == {"weight": 100, "weight_unit": "t"}


def test_parse_estimate_request_accepts_a_bare_dict():
    """Verify that parse estimate request accepts a bare dict."""
    parsed = climatiq_api._parse_estimate_request(
        {"activity_id": "steel", "parameters": {"money": 100, "money_unit": "usd"}}
    )

    assert parsed["emission_factor"]["activity_id"] == "steel"


def test_parse_estimate_request_pins_the_data_version():
    """Verify that parse estimate request pins the data version."""
    parsed = climatiq_api._parse_estimate_request(
        {"activity_id": "steel", "parameters": {"money": 1}}
    )

    assert (
        parsed["emission_factor"]["data_version"] == climatiq_api.CLIMATIQ_DATA_VERSION
    )


def test_parse_estimate_request_puts_the_selector_filters_with_the_factor():
    """Verify that parse estimate request puts the selector filters with the factor."""
    parsed = climatiq_api._parse_estimate_request(
        {
            "activity_id": "electricity-supply_grid-source_residual_mix",
            "parameters": {"energy": 500, "energy_unit": "kWh"},
            "region": "BR",
            "year": 2024,
            "region_fallback": True,
        }
    )

    factor = parsed["emission_factor"]
    assert factor["region"] == "BR"
    assert factor["year"] == 2024
    assert factor["region_fallback"] is True


def test_parse_estimate_request_keeps_the_inflation_adjustment_at_the_top_level():
    """Verify that parse estimate request keeps the inflation adjustment at the top level."""
    parsed = climatiq_api._parse_estimate_request(
        {
            "activity_id": "steel",
            "parameters": {"money": 100, "money_unit": "usd"},
            "apply_inflation_adjustment": 2021,
        }
    )

    assert parsed["apply_inflation_adjustment"] == 2021
    assert "apply_inflation_adjustment" not in parsed["emission_factor"]


def test_parse_estimate_request_rejects_a_field_climatiq_does_not_take():
    """Verify that parse estimate request rejects a field climatiq does not take."""
    with pytest.raises(ValueError) as error:
        climatiq_api._parse_estimate_request(
            {
                "activity_id": "steel",
                "parameters": {"money": 1},
                "collection": "improvement_plan",
            }
        )

    assert "collection" in str(error.value)


def test_parse_estimate_request_rejects_free_text_where_an_activity_id_belongs():
    """Verify that parse estimate request rejects free text where an activity id belongs."""
    with pytest.raises(ValueError) as error:
        climatiq_api._parse_estimate_request(
            {"text": "portland cement", "parameters": {"weight": 1}}
        )

    assert "activity_id" in str(error.value)


@pytest.mark.parametrize(
    "request_input",
    [
        {"parameters": {"money": 1}},
        {"activity_id": "", "parameters": {"money": 1}},
        {"activity_id": "   ", "parameters": {"money": 1}},
        {"activity_id": 42, "parameters": {"money": 1}},
    ],
)
def test_parse_estimate_request_rejects_a_missing_or_empty_activity_id(request_input):
    """Verify that parse estimate request rejects a missing or empty activity id."""
    with pytest.raises(ValueError) as error:
        climatiq_api._parse_estimate_request(request_input)

    assert "activity_id" in str(error.value)


@pytest.mark.parametrize(
    "request_input",
    [
        {"activity_id": "steel"},
        {"activity_id": "steel", "parameters": {}},
        {"activity_id": "steel", "parameters": "100 usd"},
    ],
)
def test_parse_estimate_request_rejects_a_missing_or_empty_quantity(request_input):
    """Verify that parse estimate request rejects a missing or empty quantity."""
    with pytest.raises(ValueError) as error:
        climatiq_api._parse_estimate_request(request_input)

    assert "parameters" in str(error.value)


@pytest.mark.parametrize(
    "request_input", ["", "   ", None, "not json", "[1, 2]", '"steel"', 42]
)
def test_parse_estimate_request_rejects_anything_that_is_not_an_object(request_input):
    """Verify that parse estimate request rejects anything that is not an object."""
    with pytest.raises(ValueError) as error:
        climatiq_api._parse_estimate_request(request_input)

    assert repr(request_input) in str(error.value)


def test_climatiq_search_gets_the_search_endpoint_with_the_agents_words(
    recorded_request,
):
    """Verify that climatiq search gets the search endpoint with the agents words."""
    climatiq_api._climatiq_search("cimento portland")

    call = recorded_request.calls[0]
    assert call["method"] == "GET"
    assert call["url"] == climatiq_api.CLIMATIQ_SEARCH_URL
    assert call["params"]["query"] == "cimento portland"


def test_climatiq_search_pins_the_data_version(recorded_request):
    """Verify that climatiq search pins the data version."""
    climatiq_api._climatiq_search("cimento portland")

    assert (
        recorded_request.calls[0]["params"]["data_version"]
        == climatiq_api.CLIMATIQ_DATA_VERSION
    )


def test_climatiq_search_bounds_how_many_factors_come_back(recorded_request):
    """Verify that climatiq search bounds how many factors come back."""
    climatiq_api._climatiq_search("cimento portland")

    assert (
        recorded_request.calls[0]["params"]["results_per_page"]
        == climatiq_api.CLIMATIQ_RESULTS_PER_PAGE
    )


def test_climatiq_search_returns_what_climatiq_answered(monkeypatch, api_key_env):
    """Verify that climatiq search returns what climatiq answered."""
    answer = {"results": [{"activity_id": "metals-type_basic_iron_and_steel"}]}
    monkeypatch.setattr(
        climatiq_api.requests, "request", RecordingRequest(FakeResponse(payload=answer))
    )

    assert climatiq_api._climatiq_search("steel") == answer


def test_climatiq_search_never_reaches_the_api_with_an_empty_query(recorded_request):
    """Verify that climatiq search never reaches the api with an empty query."""
    with pytest.raises(ValueError):
        climatiq_api._climatiq_search("   ")

    assert recorded_request.calls == []


def test_climatiq_estimate_posts_the_selector_to_the_estimate_endpoint(
    recorded_request,
):
    """Verify that climatiq estimate posts the selector to the estimate endpoint."""
    climatiq_api._climatiq_estimate(
        '{"activity_id": "metals-type_basic_iron_and_steel",'
        ' "parameters": {"weight": 100, "weight_unit": "t"}}'
    )

    call = recorded_request.calls[0]
    assert call["method"] == "POST"
    assert call["url"] == climatiq_api.CLIMATIQ_ESTIMATE_URL
    assert (
        call["json"]["emission_factor"]["activity_id"]
        == "metals-type_basic_iron_and_steel"
    )
    assert call["json"]["parameters"] == {"weight": 100, "weight_unit": "t"}


def test_climatiq_estimate_returns_what_climatiq_answered(monkeypatch, api_key_env):
    """Verify that climatiq estimate returns what climatiq answered."""
    answer = {"co2e": 65.39, "co2e_unit": "kg"}
    monkeypatch.setattr(
        climatiq_api.requests, "request", RecordingRequest(FakeResponse(payload=answer))
    )

    result = climatiq_api._climatiq_estimate(
        {"activity_id": "steel", "parameters": {"money": 100, "money_unit": "usd"}}
    )

    assert result == answer


def test_climatiq_estimate_never_reaches_the_api_with_a_malformed_request(
    recorded_request,
):
    """Verify that climatiq estimate never reaches the api with a malformed request."""
    with pytest.raises(ValueError):
        climatiq_api._climatiq_estimate("cimento portland")

    assert recorded_request.calls == []


def test_get_climatiq_tools_returns_the_search_and_estimate_tools():
    """Verify that get climatiq tools returns the search and estimate tools."""
    tools = climatiq_api.get_climatiq_tools()

    assert [type(tool) for tool in tools] == [Tool, Tool]
    assert [tool.name for tool in tools] == ["climatiq_search", "climatiq_estimate"]


def test_get_climatiq_tools_describes_both_tools_for_the_agent():
    """Verify that get climatiq tools describes both tools for the agent."""
    descriptions = {
        tool.name: tool.description for tool in climatiq_api.get_climatiq_tools()
    }

    assert descriptions["climatiq_search"] == climatiq_api.CLIMATIQ_SEARCH_DESCRIPTION
    assert (
        descriptions["climatiq_estimate"] == climatiq_api.CLIMATIQ_ESTIMATE_DESCRIPTION
    )


def test_get_climatiq_tools_entries_are_backed_by_the_climatiq_calls(recorded_request):
    """Verify that get climatiq tools entries are backed by the climatiq calls."""
    search, estimate = climatiq_api.get_climatiq_tools()

    search.func("steel")
    estimate.func(
        '{"activity_id": "steel", "parameters": {"money": 1, "money_unit": "usd"}}'
    )

    assert [call["url"] for call in recorded_request.calls] == [
        climatiq_api.CLIMATIQ_SEARCH_URL,
        climatiq_api.CLIMATIQ_ESTIMATE_URL,
    ]
