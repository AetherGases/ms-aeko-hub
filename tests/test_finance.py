"""Verify finance behavior and error handling."""

import json

import pytest
import requests
from langchain_core.tools import Tool

from cmd.api.tools import finance
from cmd.api.tools.constants import ROI_HORIZON_MONTHS


VIABLE_REQUEST = {"capex": 150, "wacc_monthly": 0.25, "cash_flows": [125, 156.25]}

ROI_SUCCESS = {
    "capex": 150,
    "wacc_monthly": 0.25,
    "months": 60,
    "vp_total": 200.0,
    "vpl": 50.0,
    "roi_percent": 33.33,
    "viable": True,
}

PAYBACK_SUCCESS = {
    "capex": 150,
    "wacc_monthly": 0.25,
    "months": 60,
    "vp_total": 200.0,
    "payback_months": 2,
    "viable": True,
}

VALIDATION_ERROR_MESSAGE = (
    '"capex" must be the initial investment, above zero, got 0.'
)


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
def investment_env(monkeypatch):
    """Set test calculator-service environment variables."""
    monkeypatch.setenv("INVESTMENT_MS_BASE_URL", "http://investment.test")
    monkeypatch.setenv("INTERNAL_AUTHENTICATION_KEY", "internal-token")
    monkeypatch.setenv("MS_HTTP_TIMEOUT", "60")


@pytest.fixture
def recorded_roi_request(monkeypatch, investment_env):
    """Replace calculator-service HTTP requests with a call recorder."""
    from cmd.api.integrations import investment_api

    request = RecordingRequest(FakeResponse(payload=ROI_SUCCESS))
    monkeypatch.setattr(investment_api.requests, "request", request)
    return request


@pytest.fixture
def recorded_payback_request(monkeypatch, investment_env):
    """Replace calculator-service HTTP requests with a payback call recorder."""
    from cmd.api.integrations import investment_api

    request = RecordingRequest(FakeResponse(payload=PAYBACK_SUCCESS))
    monkeypatch.setattr(investment_api.requests, "request", request)
    return request


class RoutingRecordingRequest:
    """Records HTTP calls and returns ROI or payback payloads by URL path."""

    def __init__(self):
        self.calls = []

    def __call__(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        if url.endswith("/calculator/payback"):
            return FakeResponse(payload=PAYBACK_SUCCESS)
        return FakeResponse(payload=ROI_SUCCESS)


@pytest.fixture
def recorded_investment_requests(monkeypatch, investment_env):
    """Record calculator-service HTTP for both ROI and payback tools."""
    from cmd.api.integrations import investment_api

    request = RoutingRecordingRequest()
    monkeypatch.setattr(investment_api.requests, "request", request)
    return request


def test_calculate_roi_posts_to_the_calculator_roi_endpoint(recorded_roi_request):
    """Verify that calculate roi posts to the calculator roi endpoint."""
    finance._calculate_roi(dict(VIABLE_REQUEST))

    call = recorded_roi_request.calls[0]
    assert call["method"] == "POST"
    assert call["url"] == "http://investment.test/calculator/roi"


def test_calculate_roi_authenticates_with_the_internal_authentication_key(
    recorded_roi_request,
):
    """Verify that calculate roi authenticates with the internal authentication key."""
    finance._calculate_roi(dict(VIABLE_REQUEST))

    headers = recorded_roi_request.calls[0]["headers"]
    assert headers["authentication-key"] == "internal-token"
    assert "Authorization" not in headers


def test_calculate_roi_never_waits_forever(recorded_roi_request):
    """Verify that calculate roi never waits forever."""
    finance._calculate_roi(dict(VIABLE_REQUEST))

    assert recorded_roi_request.calls[0]["timeout"] == 60.0


def test_calculate_roi_posts_the_same_object_from_a_json_string_or_a_dict(
    recorded_roi_request,
):
    """Verify that calculate roi posts the same object from a json string or a dict."""
    finance._calculate_roi(json.dumps(VIABLE_REQUEST))
    finance._calculate_roi(dict(VIABLE_REQUEST))

    string_body = recorded_roi_request.calls[0]["json"]
    dict_body = recorded_roi_request.calls[1]["json"]
    assert string_body == VIABLE_REQUEST
    assert dict_body == VIABLE_REQUEST
    assert string_body == dict_body


def test_calculate_roi_returns_the_service_payload_as_is(monkeypatch, investment_env):
    """Verify that calculate roi returns the service payload as is."""
    from cmd.api.integrations import investment_api

    payload = {
        "capex": 1,
        "wacc_monthly": 0,
        "months": 60,
        "vp_total": 999.99,
        "vpl": 998.99,
        "roi_percent": 99899.0,
        "viable": False,
        "extra": "from-service",
    }
    recorder = RecordingRequest(FakeResponse(payload=payload))
    monkeypatch.setattr(investment_api.requests, "request", recorder)

    answer = finance._calculate_roi(json.dumps(VIABLE_REQUEST))

    assert recorder.calls
    assert answer == payload


def test_calculate_roi_posts_an_incomplete_json_object_to_the_service(
    recorded_roi_request,
):
    """Verify that calculate roi posts an incomplete json object to the service."""
    finance._calculate_roi("{}")

    assert recorded_roi_request.calls[0]["json"] == {}


@pytest.mark.parametrize(
    "request_input",
    ["", "   ", None, 42, ["capex"], "capex: 150", "[150, 0.25]", '"150"'],
)
def test_calculate_roi_refuses_unreadable_input_without_calling_the_service(
    recorded_roi_request, request_input
):
    """Verify that calculate roi refuses unreadable input without calling the service."""
    with pytest.raises(ValueError) as error:
        finance._calculate_roi(request_input)

    assert "JSON object string" in str(error.value)
    assert repr(request_input) in str(error.value)
    assert recorded_roi_request.calls == []


def test_calculate_roi_raises_value_error_on_a_validation_error(
    monkeypatch, investment_env
):
    """Verify that calculate roi raises value error on a validation error."""
    from cmd.api.integrations import investment_api

    monkeypatch.setattr(
        investment_api.requests,
        "request",
        RecordingRequest(
            FakeResponse(
                400,
                {
                    "error_code": "validation_error",
                    "message": VALIDATION_ERROR_MESSAGE,
                },
            )
        ),
    )

    with pytest.raises(ValueError) as error:
        finance._calculate_roi(dict(VIABLE_REQUEST))

    assert str(error.value) == VALIDATION_ERROR_MESSAGE


def test_calculate_roi_raises_investment_error_on_unauthorized(
    monkeypatch, investment_env
):
    """Verify that calculate roi raises investment error on unauthorized."""
    from cmd.api.integrations import investment_api

    monkeypatch.setattr(
        investment_api.requests,
        "request",
        RecordingRequest(
            FakeResponse(
                401,
                {
                    "error_code": "unauthorized",
                    "message": "internal authentication-key was rejected",
                },
            )
        ),
    )

    with pytest.raises(investment_api.InvestmentError):
        finance._calculate_roi(dict(VIABLE_REQUEST))


@pytest.mark.parametrize(
    "error",
    [requests.Timeout("timed out"), requests.RequestException("request failed")],
)
def test_calculate_roi_raises_investment_error_when_the_service_is_never_reached(
    monkeypatch, investment_env, error
):
    """Verify that calculate roi raises investment error when the service is never reached."""
    from cmd.api.integrations import investment_api

    monkeypatch.setattr(
        investment_api.requests,
        "request",
        RecordingRequest(error=error),
    )

    with pytest.raises(investment_api.InvestmentError):
        finance._calculate_roi(dict(VIABLE_REQUEST))


def test_calculate_roi_raises_investment_error_on_a_server_error(
    monkeypatch, investment_env
):
    """Verify that calculate roi raises investment error on a server error."""
    from cmd.api.integrations import investment_api

    monkeypatch.setattr(
        investment_api.requests,
        "request",
        RecordingRequest(FakeResponse(500, {"message": "internal error"})),
    )

    with pytest.raises(investment_api.InvestmentError):
        finance._calculate_roi(dict(VIABLE_REQUEST))


def test_calculate_roi_raises_investment_error_when_a_server_error_carries_validation_error(
    monkeypatch, investment_env
):
    """Verify that calculate roi raises investment error when a server error carries validation error."""
    from cmd.api.integrations import investment_api

    monkeypatch.setattr(
        investment_api.requests,
        "request",
        RecordingRequest(
            FakeResponse(
                500,
                {
                    "error_code": "validation_error",
                    "message": VALIDATION_ERROR_MESSAGE,
                },
            )
        ),
    )

    with pytest.raises(investment_api.InvestmentError):
        finance._calculate_roi(dict(VIABLE_REQUEST))


@pytest.mark.parametrize("status_code", [200, 400])
def test_calculate_roi_raises_investment_error_when_the_answer_is_not_json(
    monkeypatch, investment_env, status_code
):
    """Verify that calculate roi raises investment error when the answer is not json."""
    from cmd.api.integrations import investment_api

    monkeypatch.setattr(
        investment_api.requests,
        "request",
        RecordingRequest(FakeResponse(status_code, None, text="not-json")),
    )

    with pytest.raises(investment_api.InvestmentError):
        finance._calculate_roi(dict(VIABLE_REQUEST))


@pytest.mark.parametrize("status_code", [200, 400])
@pytest.mark.parametrize("payload", [["roi"], "roi"])
def test_calculate_roi_raises_investment_error_on_a_non_object_json_body(
    monkeypatch, investment_env, status_code, payload
):
    """Verify that calculate roi raises investment error on a non object json body."""
    from cmd.api.integrations import investment_api

    monkeypatch.setattr(
        investment_api.requests,
        "request",
        RecordingRequest(FakeResponse(status_code, payload)),
    )

    with pytest.raises(investment_api.InvestmentError):
        finance._calculate_roi(dict(VIABLE_REQUEST))


def test_calculate_roi_raises_naming_a_missing_investment_ms_base_url(
    monkeypatch, investment_env
):
    """Verify that calculate roi raises naming a missing investment ms base url."""
    from cmd.api.integrations import investment_api

    monkeypatch.delenv("INVESTMENT_MS_BASE_URL", raising=False)
    monkeypatch.setattr(
        investment_api.requests,
        "request",
        RecordingRequest(FakeResponse(payload=ROI_SUCCESS)),
    )

    with pytest.raises(RuntimeError) as error:
        finance._calculate_roi(dict(VIABLE_REQUEST))

    assert "INVESTMENT_MS_BASE_URL" in str(error.value)


def test_calculate_roi_raises_naming_a_missing_ms_http_timeout(
    monkeypatch, investment_env
):
    """Verify that calculate roi raises naming a missing ms http timeout."""
    from cmd.api.integrations import investment_api

    monkeypatch.delenv("MS_HTTP_TIMEOUT", raising=False)
    monkeypatch.setattr(
        investment_api.requests,
        "request",
        RecordingRequest(FakeResponse(payload=ROI_SUCCESS)),
    )

    with pytest.raises(RuntimeError) as error:
        finance._calculate_roi(dict(VIABLE_REQUEST))

    assert "MS_HTTP_TIMEOUT" in str(error.value)


def test_calculate_payback_posts_to_the_calculator_payback_endpoint(
    recorded_payback_request,
):
    """Verify that calculate payback posts to the calculator payback endpoint."""
    finance._calculate_payback(dict(VIABLE_REQUEST))

    call = recorded_payback_request.calls[0]
    assert call["method"] == "POST"
    assert call["url"] == "http://investment.test/calculator/payback"


def test_calculate_payback_authenticates_with_the_internal_authentication_key(
    recorded_payback_request,
):
    """Verify that calculate payback authenticates with the internal authentication key."""
    finance._calculate_payback(dict(VIABLE_REQUEST))

    headers = recorded_payback_request.calls[0]["headers"]
    assert headers["authentication-key"] == "internal-token"
    assert "Authorization" not in headers


def test_calculate_payback_never_waits_forever(recorded_payback_request):
    """Verify that calculate payback never waits forever."""
    finance._calculate_payback(dict(VIABLE_REQUEST))

    assert recorded_payback_request.calls[0]["timeout"] == 60.0


def test_calculate_payback_posts_the_same_object_from_a_json_string_or_a_dict(
    recorded_payback_request,
):
    """Verify that calculate payback posts the same object from a json string or a dict."""
    finance._calculate_payback(json.dumps(VIABLE_REQUEST))
    finance._calculate_payback(dict(VIABLE_REQUEST))

    string_body = recorded_payback_request.calls[0]["json"]
    dict_body = recorded_payback_request.calls[1]["json"]
    assert string_body == VIABLE_REQUEST
    assert dict_body == VIABLE_REQUEST
    assert string_body == dict_body


def test_calculate_payback_returns_the_service_payload_as_is(
    monkeypatch, investment_env
):
    """Verify that calculate payback returns the service payload as is."""
    from cmd.api.integrations import investment_api

    payload = {
        "capex": 1,
        "wacc_monthly": 0,
        "months": 60,
        "vp_total": 999.99,
        "payback_months": 12,
        "viable": False,
        "extra": "from-service",
    }
    recorder = RecordingRequest(FakeResponse(payload=payload))
    monkeypatch.setattr(investment_api.requests, "request", recorder)

    answer = finance._calculate_payback(json.dumps(VIABLE_REQUEST))

    assert recorder.calls
    assert answer == payload


def test_calculate_payback_returns_the_worked_example_from_the_service(
    recorded_payback_request,
):
    """Verify that calculate payback returns the worked example from the service."""
    answer = finance._calculate_payback(json.dumps(VIABLE_REQUEST))

    assert answer == PAYBACK_SUCCESS


def test_calculate_payback_posts_an_incomplete_json_object_to_the_service(
    recorded_payback_request,
):
    """Verify that calculate payback posts an incomplete json object to the service."""
    finance._calculate_payback("{}")

    assert recorded_payback_request.calls[0]["json"] == {}


@pytest.mark.parametrize(
    "request_input",
    ["", "   ", None, 42, ["capex"], "capex: 150", "[150, 0.25]", '"150"'],
)
def test_calculate_payback_refuses_unreadable_input_without_calling_the_service(
    recorded_payback_request, request_input
):
    """Verify that calculate payback refuses unreadable input without calling the service."""
    with pytest.raises(ValueError) as error:
        finance._calculate_payback(request_input)

    assert "JSON object string" in str(error.value)
    assert repr(request_input) in str(error.value)
    assert recorded_payback_request.calls == []


def test_calculate_payback_raises_value_error_on_a_validation_error(
    monkeypatch, investment_env
):
    """Verify that calculate payback raises value error on a validation error."""
    from cmd.api.integrations import investment_api

    monkeypatch.setattr(
        investment_api.requests,
        "request",
        RecordingRequest(
            FakeResponse(
                400,
                {
                    "error_code": "validation_error",
                    "message": VALIDATION_ERROR_MESSAGE,
                },
            )
        ),
    )

    with pytest.raises(ValueError) as error:
        finance._calculate_payback(dict(VIABLE_REQUEST))

    assert str(error.value) == VALIDATION_ERROR_MESSAGE


def test_calculate_payback_raises_investment_error_on_unauthorized(
    monkeypatch, investment_env
):
    """Verify that calculate payback raises investment error on unauthorized."""
    from cmd.api.integrations import investment_api

    monkeypatch.setattr(
        investment_api.requests,
        "request",
        RecordingRequest(
            FakeResponse(
                401,
                {
                    "error_code": "unauthorized",
                    "message": "internal authentication-key was rejected",
                },
            )
        ),
    )

    with pytest.raises(investment_api.InvestmentError):
        finance._calculate_payback(dict(VIABLE_REQUEST))


@pytest.mark.parametrize(
    "error",
    [requests.Timeout("timed out"), requests.RequestException("request failed")],
)
def test_calculate_payback_raises_investment_error_when_the_service_is_never_reached(
    monkeypatch, investment_env, error
):
    """Verify that calculate payback raises investment error when the service is never reached."""
    from cmd.api.integrations import investment_api

    monkeypatch.setattr(
        investment_api.requests,
        "request",
        RecordingRequest(error=error),
    )

    with pytest.raises(investment_api.InvestmentError):
        finance._calculate_payback(dict(VIABLE_REQUEST))


def test_calculate_payback_raises_investment_error_on_a_server_error(
    monkeypatch, investment_env
):
    """Verify that calculate payback raises investment error on a server error."""
    from cmd.api.integrations import investment_api

    monkeypatch.setattr(
        investment_api.requests,
        "request",
        RecordingRequest(FakeResponse(500, {"message": "internal error"})),
    )

    with pytest.raises(investment_api.InvestmentError):
        finance._calculate_payback(dict(VIABLE_REQUEST))


def test_calculate_payback_raises_investment_error_when_a_server_error_carries_validation_error(
    monkeypatch, investment_env
):
    """Verify that calculate payback raises investment error when a server error carries validation error."""
    from cmd.api.integrations import investment_api

    monkeypatch.setattr(
        investment_api.requests,
        "request",
        RecordingRequest(
            FakeResponse(
                500,
                {
                    "error_code": "validation_error",
                    "message": VALIDATION_ERROR_MESSAGE,
                },
            )
        ),
    )

    with pytest.raises(investment_api.InvestmentError):
        finance._calculate_payback(dict(VIABLE_REQUEST))


@pytest.mark.parametrize("status_code", [200, 400])
def test_calculate_payback_raises_investment_error_when_the_answer_is_not_json(
    monkeypatch, investment_env, status_code
):
    """Verify that calculate payback raises investment error when the answer is not json."""
    from cmd.api.integrations import investment_api

    monkeypatch.setattr(
        investment_api.requests,
        "request",
        RecordingRequest(FakeResponse(status_code, None, text="not-json")),
    )

    with pytest.raises(investment_api.InvestmentError):
        finance._calculate_payback(dict(VIABLE_REQUEST))


@pytest.mark.parametrize("status_code", [200, 400])
@pytest.mark.parametrize("payload", [["payback"], "payback"])
def test_calculate_payback_raises_investment_error_on_a_non_object_json_body(
    monkeypatch, investment_env, status_code, payload
):
    """Verify that calculate payback raises investment error on a non object json body."""
    from cmd.api.integrations import investment_api

    monkeypatch.setattr(
        investment_api.requests,
        "request",
        RecordingRequest(FakeResponse(status_code, payload)),
    )

    with pytest.raises(investment_api.InvestmentError):
        finance._calculate_payback(dict(VIABLE_REQUEST))


def test_calculate_payback_raises_naming_a_missing_investment_ms_base_url(
    monkeypatch, investment_env
):
    """Verify that calculate payback raises naming a missing investment ms base url."""
    from cmd.api.integrations import investment_api

    monkeypatch.delenv("INVESTMENT_MS_BASE_URL", raising=False)
    monkeypatch.setattr(
        investment_api.requests,
        "request",
        RecordingRequest(FakeResponse(payload=PAYBACK_SUCCESS)),
    )

    with pytest.raises(RuntimeError) as error:
        finance._calculate_payback(dict(VIABLE_REQUEST))

    assert "INVESTMENT_MS_BASE_URL" in str(error.value)


def test_calculate_payback_raises_naming_a_missing_ms_http_timeout(
    monkeypatch, investment_env
):
    """Verify that calculate payback raises naming a missing ms http timeout."""
    from cmd.api.integrations import investment_api

    monkeypatch.delenv("MS_HTTP_TIMEOUT", raising=False)
    monkeypatch.setattr(
        investment_api.requests,
        "request",
        RecordingRequest(FakeResponse(payload=PAYBACK_SUCCESS)),
    )

    with pytest.raises(RuntimeError) as error:
        finance._calculate_payback(dict(VIABLE_REQUEST))

    assert "MS_HTTP_TIMEOUT" in str(error.value)


def test_get_roi_payback_tools_returns_the_two_tools_in_workflow_order():
    """Verify that get roi payback tools returns the two tools in workflow order."""
    tools = finance.get_roi_payback_tools()

    assert [tool.name for tool in tools] == ["calculate_roi", "calculate_payback"]
    assert all(isinstance(tool, Tool) for tool in tools)


def test_the_tools_carry_the_functions_that_calculate():
    """Verify that the tools carry the functions that calculate."""
    roi, payback = finance.get_roi_payback_tools()

    assert roi.func is finance._calculate_roi
    assert payback.func is finance._calculate_payback


def test_the_tool_descriptions_tell_the_agent_what_to_send_and_what_comes_back():
    """Verify that the tool descriptions tell the agent what to send and what comes back."""
    roi, payback = finance.get_roi_payback_tools()

    for description in (roi.description, payback.description):
        assert "capex" in description
        assert "wacc_monthly" in description
        assert "monthly_cash_flow" in description
        assert str(ROI_HORIZON_MONTHS) in description

    assert "-1" in payback.description


def test_the_tools_calculate_end_to_end_from_the_string_an_agent_writes(
    recorded_investment_requests,
):
    """Verify that the tools calculate end to end from the string an agent writes."""
    roi, payback = finance.get_roi_payback_tools()
    request = '{"capex": 150, "wacc_monthly": 0.25, "cash_flows": [125, 156.25]}'

    assert roi.func(request)["roi_percent"] == 33.33
    assert payback.func(request)["payback_months"] == 2
    assert len(recorded_investment_requests.calls) == 2
