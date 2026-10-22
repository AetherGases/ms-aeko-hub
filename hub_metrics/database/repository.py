"""Persist and retrieve HTTP request metrics through MongoDB."""

from hub_metrics.constants import COLLECTION
from hub_metrics.database import query as q
from hub_metrics.entity import Metric
from hub_metrics.hub_metrics import IRepository
from internal.shared import Module, logged


class Repository(IRepository):
    def __init__(self, db):
        """Bind the MongoDB database handle."""
        self.db = db

    @logged(Module.DATABASE, "hub_metrics.create_metric")
    def create_metric(self, metric: Metric) -> Metric:
        """Persist a metric and return it with its database identifier."""
        try:
            result = self.db[COLLECTION].insert_one(q.create_metric_query(metric))
            metric.id = str(result.inserted_id)
            return metric
        except Exception as e:
            raise RuntimeError(f"Error creating metric in database: {e}")

    @logged(Module.DATABASE, "hub_metrics.get_all_metrics")
    def get_all_metrics(self) -> list[Metric]:
        """Retrieve all stored metrics."""
        try:
            query, projection = q.get_all_metrics_query()
            return [
                metric_from_data(data)
                for data in self.db[COLLECTION].find(query, projection)
            ]
        except Exception as e:
            raise RuntimeError(f"Error fetching metrics from database: {e}")


def metric_from_data(data: dict) -> Metric:
    """Map a stored document to a metric, using defaults for missing optional fields."""
    return Metric(
        id=str(data.get("_id")) if data.get("_id") is not None else None,
        latency=data.get("latency", ""),
        response_status=data.get("response_status", 0),
        endpoint=data.get("endpoint", ""),
        origin=data.get("origin", "internal"),
        created_at=data.get("created_at"),
    )
