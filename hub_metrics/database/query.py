"""Build MongoDB filters and documents for HTTP request metrics."""

from datetime import datetime

from hub_metrics.entity import Metric
from internal.database.object_id import normalize_id


def create_metric_query(metric: Metric) -> dict:
    """Build a request metric document, preserving its identifier when supplied."""

    document = {
        "latency": metric.latency,
        "response_status": metric.response_status,
        "endpoint": metric.endpoint,
        "origin": metric.origin,
        "created_at": metric.created_at or datetime.utcnow(),
    }

    if metric.id is not None:
        document["_id"] = normalize_id(metric.id)

    return document


def get_all_metrics_query() -> tuple[dict, dict]:
    """Return a filter and projection that include all metric documents and fields."""
    return {}, {}
