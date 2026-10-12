"""Export gateway and SDK metrics through OpenTelemetry for Dynatrace dashboards."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from opentelemetry import metrics
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics._internal.instrument import (
    Counter,
    Histogram,
    ObservableCounter,
    ObservableUpDownCounter,
    UpDownCounter,
)
from opentelemetry.sdk.metrics.export import AggregationTemporality, PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource

if TYPE_CHECKING:
    from aeko_metrics.entity import Metric as AekoMetric
    from hub_metrics.entity import Metric as HubMetric

_meter = None
_provider: MeterProvider | None = None
_hub_requests = None
_hub_latency = None
_aeko_runs = None
_aeko_latency = None
_aeko_cost = None
_aeko_agent_invocations = None
_aeko_tool_invocations = None

_HUB_REQUESTS = "aether.hub.requests"
_HUB_LATENCY_MS = "aether.hub.request.latency_ms"
_AEKO_RUNS = "aether.aeko.runs"
_AEKO_LATENCY_MS = "aether.aeko.run.latency_ms"
_AEKO_COST_USD = "aether.aeko.run.cost_usd"
_AEKO_AGENT_INVOCATIONS = "aether.aeko.agent.invocations"
_AEKO_TOOL_INVOCATIONS = "aether.aeko.tool.invocations"


def _latency_ms(value: str) -> float:
    text = value.strip()
    if text.endswith("ms"):
        try:
            return float(text[:-2])
        except ValueError:
            return 0.0
    return 0.0


def _parse_headers(raw: str) -> dict[str, str]:
    headers: dict[str, str] = {}
    for part in raw.split(","):
        piece = part.strip()
        if not piece or "=" not in piece:
            continue
        key, value = piece.split("=", 1)
        headers[key.strip()] = value.strip()
    return headers


def _dynatrace_authorization(token: str) -> str:
    value = token.strip()
    if not value:
        return ""
    lowered = value.lower()
    if lowered.startswith("bearer ") or lowered.startswith("api-token "):
        return value
    return f"Bearer {value}"


def _otlp_auth_headers() -> dict[str, str] | None:
    raw = os.getenv("OTEL_EXPORTER_OTLP_HEADERS", "").strip()
    if raw:
        parsed = _parse_headers(raw)
        return parsed or None
    token = os.getenv("DT_PLATFORM_TOKEN", "").strip()
    if token:
        return {"Authorization": _dynatrace_authorization(token)}
    return None


def _dynatrace_delta_temporality() -> dict[type, AggregationTemporality]:
    """Dynatrace OTLP ingest requires delta aggregation temporality."""
    delta = AggregationTemporality.DELTA
    return {
        Counter: delta,
        UpDownCounter: delta,
        Histogram: delta,
        ObservableCounter: delta,
        ObservableUpDownCounter: delta,
    }


def _normalize_metrics_endpoint(endpoint: str) -> str:
    url = endpoint.strip().rstrip("/")
    if not url:
        return url
    if url.endswith("/v1/metrics"):
        return url
    if url.endswith("/api/v2/otlp"):
        return f"{url}/v1/metrics"
    return url


def configure(metric_reader=None) -> None:
    """Install the process-wide meter provider, optionally exporting OTLP metrics.

    Defaults OTLP metric temporality to DELTA because Dynatrace OTLP rejects cumulative counters.
    """
    global _meter, _provider, _hub_requests, _hub_latency, _aeko_runs, _aeko_latency, _aeko_cost
    global _aeko_agent_invocations, _aeko_tool_invocations

    if _provider is not None:
        return

    os.environ.setdefault("OTEL_EXPORTER_OTLP_METRICS_TEMPORALITY_PREFERENCE", "DELTA")

    service_name = os.getenv("OTEL_SERVICE_NAME", "").strip() or os.getenv("APP_NAME", "aeko-hub")
    resource = Resource.create({"service.name": service_name})

    readers = []
    if metric_reader is not None:
        readers.append(metric_reader)
    else:
        endpoint = _normalize_metrics_endpoint(os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip())
        if endpoint:
            headers = _otlp_auth_headers()
            interval_ms = int(os.getenv("OTEL_METRIC_EXPORT_INTERVAL_MS", "60000"))
            exporter = OTLPMetricExporter(
                endpoint=endpoint,
                headers=headers or None,
                preferred_temporality=_dynatrace_delta_temporality(),
            )
            readers.append(
                PeriodicExportingMetricReader(exporter, export_interval_millis=interval_ms)
            )

    _provider = MeterProvider(resource=resource, metric_readers=readers)
    metrics.set_meter_provider(_provider)
    _meter = metrics.get_meter("aether.aeko-hub")
    _hub_requests = _meter.create_counter(_HUB_REQUESTS)
    _hub_latency = _meter.create_histogram(_HUB_LATENCY_MS, unit="ms")
    _aeko_runs = _meter.create_counter(_AEKO_RUNS)
    _aeko_latency = _meter.create_histogram(_AEKO_LATENCY_MS, unit="ms")
    _aeko_cost = _meter.create_histogram(_AEKO_COST_USD, unit="USD")
    _aeko_agent_invocations = _meter.create_counter(_AEKO_AGENT_INVOCATIONS)
    _aeko_tool_invocations = _meter.create_counter(_AEKO_TOOL_INVOCATIONS)


def shutdown() -> None:
    """Flush and tear down the configured meter provider."""
    global _provider, _meter, _hub_requests, _hub_latency, _aeko_runs, _aeko_latency, _aeko_cost
    global _aeko_agent_invocations, _aeko_tool_invocations
    if _provider is None:
        return
    _provider.shutdown()
    _provider = None
    _meter = None
    _hub_requests = None
    _hub_latency = None
    _aeko_runs = None
    _aeko_latency = None
    _aeko_cost = None
    _aeko_agent_invocations = None
    _aeko_tool_invocations = None


def record_hub_metric(metric: HubMetric) -> None:
    """Record one persisted HTTP request metric."""
    if _hub_requests is None or _hub_latency is None:
        return
    attributes = {
        "endpoint": metric.endpoint,
        "response_status": str(metric.response_status),
        "origin": metric.origin,
    }
    _hub_requests.add(1, attributes)
    _hub_latency.record(_latency_ms(metric.latency), attributes)


def record_aeko_run(metric: AekoMetric) -> None:
    """Record one persisted SDK run metric."""
    if _aeko_runs is None or _aeko_latency is None or _aeko_cost is None:
        return
    attributes = {
        "flow": metric.flow,
        "failed": metric.error_description is not None,
    }
    if metric.id_request:
        attributes["request_id"] = metric.id_request
    if metric.id_external_company is not None:
        attributes["id_external_company"] = metric.id_external_company
    if metric.id_external_user is not None:
        attributes["id_external_user"] = metric.id_external_user
    _aeko_runs.add(1, attributes)
    _aeko_latency.record(metric.latency, attributes)
    _aeko_cost.record(metric.cost_usd, attributes)

    if _aeko_agent_invocations is None or _aeko_tool_invocations is None:
        return

    for agent in metric.used_agents:
        agent_attrs = {
            "agent_name": agent.name,
            "flow": metric.flow,
            "failed": metric.error_description is not None,
        }
        if metric.id_external_company is not None:
            agent_attrs["id_external_company"] = metric.id_external_company
        _aeko_agent_invocations.add(1, agent_attrs)
        for tool_name in agent.used_tools:
            tool_attrs = {
                "tool_name": tool_name,
                "agent_name": agent.name,
                "flow": metric.flow,
                "failed": metric.error_description is not None,
            }
            _aeko_tool_invocations.add(1, tool_attrs)
