"""Verify finance behavior and error handling."""

import json

import pytest
import requests
from langchain_core.tools import Tool

from cmd.api.tools import finance


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


def request_without(field, **overrides):
    """Build a financial request with the selected field omitted."""
    request = {key: value for key, value in VIABLE_REQUEST.items() if key != field}
    request.update(overrides)
    return request


def test_parse_request_reads_a_json_object_string():
    """Verify that parse request reads a json object string."""
    assert finance._parse_request(json.dumps(VIABLE_REQUEST)) == {
        "capex": 150,
        "wacc_monthly": 0.25,
        "cash_flows": [125, 156.25] + [0] * 58,
    }


def test_parse_request_also_takes_the_object_itself():
    """Verify that parse request also takes the object itself."""
    assert finance._parse_request(dict(VIABLE_REQUEST))["capex"] == 150


@pytest.mark.parametrize(
    "request_input",
    ["", "   ", None, 42, ["capex"], "capex: 150", "[150, 0.25]", '"150"'],
)
def test_parse_request_rejects_anything_that_is_not_a_json_object(request_input):
    """Verify that parse request rejects anything that is not a json object."""
    with pytest.raises(ValueError) as error:
        finance._parse_request(request_input)

    assert repr(request_input) in str(error.value)


def test_parse_request_rejects_a_field_it_does_not_know_naming_it():
    """Verify that parse request rejects a field it does not know naming it."""
    with pytest.raises(ValueError) as error:
        finance._parse_request(dict(VIABLE_REQUEST, discount_rate=0.1, tax=0.3))

    assert "discount_rate" in str(error.value)
    assert "tax" in str(error.value)


@pytest.mark.parametrize(
    "capex", [None, "150", True, [150], float("inf"), float("nan")]
)
def test_parse_request_rejects_a_capex_that_is_not_a_real_number(capex):
    """Verify that parse request rejects a capex that is not a real number."""
    with pytest.raises(ValueError) as error:
        finance._parse_request(request_without("capex", capex=capex))

    assert "capex" in str(error.value)


@pytest.mark.parametrize("capex", [0, -1, -0.5])
def test_parse_request_rejects_a_capex_that_is_not_above_zero(capex):
    """Verify that parse request rejects a capex that is not above zero."""
    with pytest.raises(ValueError) as error:
        finance._parse_request(request_without("capex", capex=capex))

    assert "capex" in str(error.value)


def test_parse_request_keeps_the_capex_as_it_was_given():
    """Verify that parse request keeps the capex as it was given."""
    parsed = finance._parse_request(request_without("capex", capex=1234.56))

    assert parsed["capex"] == 1234.56


@pytest.mark.parametrize("wacc", [None, "0.01", True, float("inf")])
def test_parse_request_rejects_a_wacc_that_is_not_a_real_number(wacc):
    """Verify that parse request rejects a wacc that is not a real number."""
    with pytest.raises(ValueError) as error:
        finance._parse_request(request_without("wacc_monthly", wacc_monthly=wacc))

    assert "wacc_monthly" in str(error.value)


@pytest.mark.parametrize("wacc", [-0.01, 1, 1.5, 12])
def test_parse_request_rejects_a_wacc_outside_the_monthly_range(wacc):
    """Verify that parse request rejects a wacc outside the monthly range."""
    with pytest.raises(ValueError) as error:
        finance._parse_request(request_without("wacc_monthly", wacc_monthly=wacc))

    assert "wacc_monthly" in str(error.value)


def test_parse_request_accepts_a_wacc_of_zero():
    """Verify that parse request accepts a wacc of zero."""
    parsed = finance._parse_request(request_without("wacc_monthly", wacc_monthly=0))

    assert parsed["wacc_monthly"] == 0


def test_parse_request_pads_a_short_list_of_flows_to_the_horizon():
    """Verify that parse request pads a short list of flows to the horizon."""
    parsed = finance._parse_request(
        request_without("cash_flows", cash_flows=[125, 156.25])
    )

    assert len(parsed["cash_flows"]) == finance.ROI_HORIZON_MONTHS
    assert parsed["cash_flows"][:2] == [125, 156.25]
    assert set(parsed["cash_flows"][2:]) == {0}


def test_parse_request_repeats_a_single_monthly_flow_over_the_horizon():
    """Verify that parse request repeats a single monthly flow over the horizon."""
    parsed = finance._parse_request(
        request_without("cash_flows", monthly_cash_flow=5000)
    )

    assert parsed["cash_flows"] == [5000] * finance.ROI_HORIZON_MONTHS


def test_parse_request_accepts_a_full_horizon_of_flows():
    """Verify that parse request accepts a full horizon of flows."""
    flows = list(range(1, finance.ROI_HORIZON_MONTHS + 1))

    parsed = finance._parse_request(request_without("cash_flows", cash_flows=flows))

    assert parsed["cash_flows"] == flows


def test_parse_request_accepts_a_negative_flow():
    """Verify that parse request accepts a negative flow."""
    parsed = finance._parse_request(
        request_without("cash_flows", cash_flows=[-500, 125])
    )

    assert parsed["cash_flows"][:2] == [-500, 125]


def test_parse_request_rejects_both_ways_of_giving_the_flows_at_once():
    """Verify that parse request rejects both ways of giving the flows at once."""
    with pytest.raises(ValueError) as error:
        finance._parse_request(dict(VIABLE_REQUEST, monthly_cash_flow=5000))

    assert "cash_flows" in str(error.value)
    assert "monthly_cash_flow" in str(error.value)


def test_parse_request_rejects_a_request_with_no_flows_at_all():
    """Verify that parse request rejects a request with no flows at all."""
    with pytest.raises(ValueError) as error:
        finance._parse_request(request_without("cash_flows"))

    assert "cash_flows" in str(error.value)
    assert "monthly_cash_flow" in str(error.value)


@pytest.mark.parametrize("flows", [[], "125, 156.25", 125, {"1": 125}])
def test_parse_request_rejects_flows_that_are_not_a_non_empty_list(flows):
    """Verify that parse request rejects flows that are not a non empty list."""
    with pytest.raises(ValueError) as error:
        finance._parse_request(request_without("cash_flows", cash_flows=flows))

    assert "cash_flows" in str(error.value)


def test_parse_request_rejects_more_flows_than_months_in_the_horizon():
    """Verify that parse request rejects more flows than months in the horizon."""
    flows = [1] * (finance.ROI_HORIZON_MONTHS + 1)

    with pytest.raises(ValueError) as error:
        finance._parse_request(request_without("cash_flows", cash_flows=flows))

    assert str(finance.ROI_HORIZON_MONTHS) in str(error.value)


@pytest.mark.parametrize("flow", ["125", None, True, [125], float("inf")])
def test_parse_request_rejects_a_flow_that_is_not_a_real_number(flow):
    """Verify that parse request rejects a flow that is not a real number."""
    with pytest.raises(ValueError) as error:
        finance._parse_request(request_without("cash_flows", cash_flows=[125, flow]))

    assert "cash_flows" in str(error.value)


@pytest.mark.parametrize("flow", ["5000", None, True])
def test_parse_request_rejects_a_single_monthly_flow_that_is_not_a_number(flow):
    """Verify that parse request rejects a single monthly flow that is not a number."""
    with pytest.raises(ValueError) as error:
        finance._parse_request(request_without("cash_flows", monthly_cash_flow=flow))

    assert "monthly_cash_flow" in str(error.value)


def test_present_values_discounts_each_month_by_its_own_factor():
    """Verify that present values discounts each month by its own factor."""
    assert finance._present_values([125, 156.25], 0.25) == [100.0, 100.0]


def test_present_values_starts_the_exponent_at_the_first_month():
    """Verify that present values starts the exponent at the first month."""
    assert finance._present_values([125], 0.25) == [100.0]


def test_present_values_leaves_the_flows_alone_when_the_wacc_is_zero():
    """Verify that present values leaves the flows alone when the wacc is zero."""
    assert finance._present_values([100, 200, 300], 0) == [100, 200, 300]


def test_present_values_discounts_a_negative_flow_the_same_way():
    """Verify that present values discounts a negative flow the same way."""
    assert finance._present_values([-125], 0.25) == [-100.0]


def test_present_values_of_no_flows_is_no_present_values():
    """Verify that present values of no flows is no present values."""
    assert finance._present_values([], 0.25) == []


def test_present_values_matches_the_formula_over_the_whole_horizon():
    """Verify that present values matches the formula over the whole horizon."""
    flows = [1000] * finance.ROI_HORIZON_MONTHS

    present_values = finance._present_values(flows, 0.01)

    assert present_values == pytest.approx(
        [1000 / 1.01**month for month in range(1, finance.ROI_HORIZON_MONTHS + 1)]
    )


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


def test_calculate_payback_answers_the_first_month_that_covers_the_capex():
    """Verify that calculate payback answers the first month that covers the capex."""
    assert finance._calculate_payback(json.dumps(VIABLE_REQUEST)) == {
        "capex": 150,
        "wacc_monthly": 0.25,
        "months": finance.ROI_HORIZON_MONTHS,
        "vp_total": 200.0,
        "payback_months": 2,
        "viable": True,
    }


def test_calculate_payback_counts_a_month_that_matches_the_capex_exactly():
    """Verify that calculate payback counts a month that matches the capex exactly."""
    answer = finance._calculate_payback(
        {"capex": 100, "wacc_monthly": 0.25, "cash_flows": [125]}
    )

    assert answer["payback_months"] == 1


def test_calculate_payback_answers_minus_one_when_the_capex_never_comes_back():
    """Verify that calculate payback answers minus one when the capex never comes back."""
    answer = finance._calculate_payback(dict(VIABLE_REQUEST, capex=250))

    assert answer["payback_months"] == finance.ROI_PAYBACK_NOT_RECOVERED
    assert answer["payback_months"] == -1
    assert answer["viable"] is False


def test_calculate_payback_does_not_discount_when_the_wacc_is_zero():
    """Verify that calculate payback does not discount when the wacc is zero."""
    answer = finance._calculate_payback(
        {"capex": 250, "wacc_monthly": 0, "cash_flows": [100, 200, 300]}
    )

    assert answer["payback_months"] == 2
    assert answer["vp_total"] == 600.0


def test_calculate_payback_waits_for_the_accumulated_value_and_not_the_monthly_one():
    """Verify that calculate payback waits for the accumulated value and not the monthly one."""
    answer = finance._calculate_payback(
        {"capex": 290, "wacc_monthly": 0, "cash_flows": [100, 100, 100]}
    )

    assert answer["payback_months"] == 3


def test_calculate_payback_reaches_the_last_month_of_the_horizon():
    """Verify that calculate payback reaches the last month of the horizon."""
    answer = finance._calculate_payback(
        {"capex": 150000, "wacc_monthly": 0.01, "monthly_cash_flow": 5000}
    )
    accumulated = 0.0
    expected = -1
    for month in range(1, 61):
        accumulated += 5000 / 1.01**month
        if accumulated >= 150000:
            expected = month
            break

    assert answer["payback_months"] == expected


def test_calculate_payback_can_find_a_month_in_a_project_that_is_not_viable():
    """Verify that calculate payback can find a month in a project that is not viable."""
    flows = [200] * 30 + [-6000] + [200] * 29

    answer = finance._calculate_payback(
        {"capex": 5900, "wacc_monthly": 0, "cash_flows": flows}
    )

    assert answer["payback_months"] == 30
    assert answer["vp_total"] == 5800.0
    assert answer["viable"] is False


def test_calculate_payback_refuses_a_request_it_cannot_read():
    """Verify that calculate payback refuses a request it cannot read."""
    with pytest.raises(ValueError) as error:
        finance._calculate_payback("{}")

    assert "capex" in str(error.value)


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
        assert str(finance.ROI_HORIZON_MONTHS) in description

    assert "-1" in payback.description


def test_the_tools_calculate_end_to_end_from_the_string_an_agent_writes(
    recorded_roi_request,
):
    """Verify that the tools calculate end to end from the string an agent writes."""
    roi, payback = finance.get_roi_payback_tools()
    request = '{"capex": 150, "wacc_monthly": 0.25, "cash_flows": [125, 156.25]}'

    assert roi.func(request)["roi_percent"] == 33.33
    assert payback.func(request)["payback_months"] == 2
    assert recorded_roi_request.calls
