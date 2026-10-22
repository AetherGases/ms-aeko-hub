"""Verify OpenTelemetry metric export hooks."""

import os
from datetime import datetime
from types import SimpleNamespace

from aeko_metrics.entity import AgentMetric, Metric as AekoMetric
from hub_metrics.entity import Metric as HubMetric
from internal.observability import telemetry
from internal.observability.telemetry import (
    _dynatrace_authorization,
    _latency_ms,
    _normalize_metrics_endpoint,
    _otlp_auth_headers,
    _parse_headers,
)


def test_latency_ms_parses_milliseconds_and_rejects_invalid_values():
    """Verify that hub latency strings are parsed and invalid values become zero."""
    assert _latency_ms("10.5ms") == 10.5
    assert _latency_ms("not-a-number-ms") == 0.0
    assert _latency_ms("5s") == 0.0


def test_parse_headers_skips_malformed_segments():
    """Verify that malformed OTLP header segments are ignored."""
    assert _parse_headers("Authorization=Bearer x, bad, key=value") == {
        "Authorization": "Bearer x",
        "key": "value",
    }


def test_dynatrace_authorization_preserves_existing_scheme():
    """Verify that existing Authorization schemes are preserved for Dynatrace OTLP."""
    assert _dynatrace_authorization("Bearer tok") == "Bearer tok"
    assert _dynatrace_authorization("api-token tok") == "api-token tok"
    assert _dynatrace_authorization("") == ""


def test_otlp_auth_headers_prefers_explicit_headers(monkeypatch):
    """Verify that OTEL_EXPORTER_OTLP_HEADERS overrides the platform token."""
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_HEADERS", "Authorization=Bearer explicit")
    monkeypatch.setenv("DT_PLATFORM_TOKEN", "ignored")
    assert _otlp_auth_headers() == {"Authorization": "Bearer explicit"}


def test_otlp_auth_headers_returns_none_when_headers_parse_empty(monkeypatch):
    """Verify that empty OTLP header parsing yields no auth headers."""
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_HEADERS", "not-a-header")
    monkeypatch.delenv("DT_PLATFORM_TOKEN", raising=False)
    assert _otlp_auth_headers() is None


def test_normalize_metrics_endpoint_appends_metrics_suffix_for_otlp_base():
    """Verify that Dynatrace OTLP base URLs gain the metrics path suffix."""
    assert _normalize_metrics_endpoint("https://dt.example/api/v2/otlp") == (
        "https://dt.example/api/v2/otlp/v1/metrics"
    )
    assert _normalize_metrics_endpoint("https://dt.example/api/v2/otlp/v1/metrics") == (
        "https://dt.example/api/v2/otlp/v1/metrics"
    )
    assert _normalize_metrics_endpoint("") == ""


def test_platform_token_uses_bearer_authorization():
    """Verify that Dynatrace platform tokens use the Bearer scheme for OTLP."""
    assert _dynatrace_authorization("dt0c01.example") == "Bearer dt0c01.example"


def test_configure_is_idempotent_when_already_configured(monkeypatch):
    """Verify that configure does not replace an existing meter provider."""
    telemetry.shutdown()
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    try:
        telemetry.configure()
        provider = telemetry._provider
        telemetry.configure()
        assert telemetry._provider is provider
    finally:
        telemetry.shutdown()


def test_configure_accepts_an_injected_metric_reader(monkeypatch):
    """Verify that configure wires an injected in-memory metric reader."""
    from opentelemetry.sdk.metrics.export import InMemoryMetricReader

    telemetry.shutdown()
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    try:
        telemetry.configure(metric_reader=InMemoryMetricReader())
        assert telemetry._provider is not None
    finally:
        telemetry.shutdown()


def test_configure_builds_otlp_exporter_when_endpoint_is_set(monkeypatch):
    """Verify that configure builds an OTLP exporter when an endpoint is configured."""
    telemetry.shutdown()
    captured = []

    class FakeExporter:
        _preferred_temporality = {}
        _preferred_aggregation = {}

        def __init__(self, endpoint, headers, preferred_temporality):
            captured.append((endpoint, headers, preferred_temporality))

        def shutdown(self, *args, **kwargs):
            """No-op shutdown hook for the OTLP exporter test double."""
            return None

    monkeypatch.setattr(telemetry, "OTLPMetricExporter", FakeExporter)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "https://dt.example/api/v2/otlp")
    monkeypatch.setenv("OTEL_METRIC_EXPORT_INTERVAL_MS", "5000")
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_HEADERS", raising=False)
    monkeypatch.setenv("DT_PLATFORM_TOKEN", "dt0c01.example")
    try:
        telemetry.configure()
        assert captured[0][0] == "https://dt.example/api/v2/otlp/v1/metrics"
        assert captured[0][1] == {"Authorization": "Bearer dt0c01.example"}
    finally:
        telemetry.shutdown()


def test_otlp_auth_headers_returns_none_without_token_or_headers(monkeypatch):
    """Verify that OTLP auth headers are omitted when no token or headers are set."""
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_HEADERS", raising=False)
    monkeypatch.delenv("DT_PLATFORM_TOKEN", raising=False)
    assert _otlp_auth_headers() is None


def test_normalize_metrics_endpoint_returns_custom_urls_unchanged():
    """Verify that non-Dynatrace collector URLs are left unchanged."""
    assert _normalize_metrics_endpoint("https://collector.example/otlp") == (
        "https://collector.example/otlp"
    )


def test_configure_prefers_delta_metric_temporality_for_dynatrace(monkeypatch):
    """Verify that OTLP export defaults to DELTA temporality required by Dynatrace."""
    telemetry.shutdown()
    monkeypatch.delenv(
        "OTEL_EXPORTER_OTLP_METRICS_TEMPORALITY_PREFERENCE", raising=False
    )
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    try:
        telemetry.configure()
        assert os.getenv("OTEL_EXPORTER_OTLP_METRICS_TEMPORALITY_PREFERENCE") == "DELTA"
    finally:
        telemetry.shutdown()


def test_dt_platform_token_builds_otlp_headers(monkeypatch):
    """Verify that DT_PLATFORM_TOKEN is used when OTEL_EXPORTER_OTLP_HEADERS is unset."""
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_HEADERS", raising=False)
    monkeypatch.setenv("DT_PLATFORM_TOKEN", "dt0c01.example")
    headers = _otlp_auth_headers()
    assert headers == {"Authorization": "Bearer dt0c01.example"}


def test_record_hub_metric_is_a_no_op_before_configure():
    """Verify that recording is skipped until OpenTelemetry is configured."""
    telemetry.record_hub_metric(
        HubMetric(
            latency="1ms", response_status=200, endpoint="/ai/user/{id_external_user}"
        )
    )


def test_record_hub_metric_forwards_attributes_to_otel():
    """Verify that hub metric fields map to OTLP counter and histogram attributes."""
    counter = SimpleNamespace(
        calls=[], add=lambda value, attrs: counter.calls.append((value, attrs))
    )
    histogram = SimpleNamespace(
        calls=[], record=lambda value, attrs: histogram.calls.append((value, attrs))
    )
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
                "response_status": "201",
                "origin": "openai",
            },
        )
    ]
    assert histogram.calls[0][0] == 10.5


def test_record_aeko_run_forwards_attributes_to_otel():
    """Verify that SDK run fields map to OTLP counters and histograms."""
    counter = SimpleNamespace(
        calls=[], add=lambda value, attrs: counter.calls.append((value, attrs))
    )
    latency = SimpleNamespace(
        calls=[], record=lambda value, attrs: latency.calls.append((value, attrs))
    )
    cost = SimpleNamespace(
        calls=[], record=lambda value, attrs: cost.calls.append((value, attrs))
    )
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


def test_record_aeko_run_exports_agent_and_tool_invocations():
    """Verify used_agents / used_tools map to OTLP invocation counters."""
    runs = SimpleNamespace(
        calls=[], add=lambda value, attrs: runs.calls.append((value, attrs))
    )
    latency = SimpleNamespace(
        calls=[], record=lambda value, attrs: latency.calls.append((value, attrs))
    )
    cost = SimpleNamespace(
        calls=[], record=lambda value, attrs: cost.calls.append((value, attrs))
    )
    agents = SimpleNamespace(
        calls=[], add=lambda value, attrs: agents.calls.append((value, attrs))
    )
    tools = SimpleNamespace(
        calls=[], add=lambda value, attrs: tools.calls.append((value, attrs))
    )
    telemetry._aeko_runs = runs
    telemetry._aeko_latency = latency
    telemetry._aeko_cost = cost
    telemetry._aeko_agent_invocations = agents
    telemetry._aeko_tool_invocations = tools
    try:
        telemetry.record_aeko_run(
            AekoMetric(
                id_request="req-2",
                latency=100,
                error_description=None,
                flow="analytical",
                cost_usd=0.01,
                used_agents=[
                    AgentMetric(
                        name="planner",
                        used_tools=["search", "calc"],
                    ),
                    AgentMetric(name="writer", used_tools=[]),
                ],
                id_external_company=1,
            )
        )
    finally:
        telemetry._aeko_runs = None
        telemetry._aeko_latency = None
        telemetry._aeko_cost = None
        telemetry._aeko_agent_invocations = None
        telemetry._aeko_tool_invocations = None

    assert len(agents.calls) == 2
    assert agents.calls[0][1]["agent_name"] == "planner"
    assert agents.calls[0][1]["flow"] == "analytical"
    assert len(tools.calls) == 2
    assert tools.calls[0][1] == {
        "tool_name": "search",
        "agent_name": "planner",
        "flow": "analytical",
        "failed": False,
    }


def test_record_aeko_run_is_a_no_op_before_configure():
    """Verify that SDK run recording is skipped until OpenTelemetry is configured."""
    telemetry.record_aeko_run(
        AekoMetric(id_request="req-0", latency=1, flow="conversational", used_agents=[])
    )


def test_record_aeko_run_skips_agent_counters_when_not_configured():
    """Verify that run metrics still export when agent/tool counters are absent."""
    runs = SimpleNamespace(
        calls=[], add=lambda value, attrs: runs.calls.append((value, attrs))
    )
    latency = SimpleNamespace(
        calls=[], record=lambda value, attrs: latency.calls.append((value, attrs))
    )
    cost = SimpleNamespace(
        calls=[], record=lambda value, attrs: cost.calls.append((value, attrs))
    )
    telemetry._aeko_runs = runs
    telemetry._aeko_latency = latency
    telemetry._aeko_cost = cost
    telemetry._aeko_agent_invocations = None
    telemetry._aeko_tool_invocations = None
    try:
        telemetry.record_aeko_run(
            AekoMetric(
                id_request="req-3",
                latency=50,
                flow="conversational",
                used_agents=[AgentMetric(name="FAQ", used_tools=["calc"])],
            )
        )
    finally:
        telemetry._aeko_runs = None
        telemetry._aeko_latency = None
        telemetry._aeko_cost = None

    assert len(runs.calls) == 1
