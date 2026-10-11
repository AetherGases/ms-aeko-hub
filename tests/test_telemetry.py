"""Verify OpenTelemetry metric export hooks."""

from datetime import datetime
from types import SimpleNamespace

from aeko_metrics.entity import AgentMetric, Metric as AekoMetric
from hub_metrics.entity import Metric as HubMetric
from internal.observability import telemetry


def test_record_hub_metric_is_a_no_op_before_configure():
    """Verify that recording is skipped until OpenTelemetry is configured."""
    telemetry.record_hub_metric(
        HubMetric(latency="1ms", response_status=200, endpoint="/ai/user/{id_external_user}")
    )


def test_record_hub_metric_forwards_attributes_to_otel():
    """Verify that hub metric fields map to OTLP counter and histogram attributes."""
    counter = SimpleNamespace(calls=[], add=lambda value, attrs: counter.calls.append((value, attrs)))
    histogram = SimpleNamespace(calls=[], record=lambda value, attrs: histogram.calls.append((value, attrs)))
    telemetry._hub_requests = counter
    telemetry._hub_latency = histogram
    try:
        telemetry.record_hub_metric(
            HubMetric(
                latency="10.5ms",
                response_status=201,
                endpoint="/ai/user/{id_external_user}",
                id="req-1",
                origin="openai",
            )
        )
    finally:
        telemetry._hub_requests = None
        telemetry._hub_latency = None

    assert counter.calls == [
        (
            1,
            {
                "endpoint": "/ai/user/{id_external_user}",
                "response_status": 201,
                "origin": "openai",
                "request_id": "req-1",
            },
        )
    ]
    assert histogram.calls[0][0] == 10.5


def test_record_aeko_run_forwards_attributes_to_otel():
    """Verify that SDK run fields map to OTLP counters and histograms."""
    counter = SimpleNamespace(calls=[], add=lambda value, attrs: counter.calls.append((value, attrs)))
    latency = SimpleNamespace(calls=[], record=lambda value, attrs: latency.calls.append((value, attrs)))
    cost = SimpleNamespace(calls=[], record=lambda value, attrs: cost.calls.append((value, attrs)))
    telemetry._aeko_runs = counter
    telemetry._aeko_latency = latency
    telemetry._aeko_cost = cost
    try:
        telemetry.record_aeko_run(
            AekoMetric(
                id_request="req-1",
                latency=4823,
                error_description=None,
                flow="conversational",
                cost_usd=0.02,
                used_agents=[
                    AgentMetric(
                        name="agent",
                        input_tokens=1,
                        output_tokens=2,
                        llm="gemini-3.5-flash",
                        used_tools=[],
                    )
                ],
                id_external_user=12345,
                id_external_company=90,
                created_at=datetime(2026, 3, 10),
            )
        )
    finally:
        telemetry._aeko_runs = None
        telemetry._aeko_latency = None
        telemetry._aeko_cost = None

    assert counter.calls[0][1]["flow"] == "conversational"
    assert counter.calls[0][1]["failed"] is False
    assert counter.calls[0][1]["id_external_company"] == 90
    assert latency.calls[0][0] == 4823
    assert cost.calls[0][0] == 0.02
