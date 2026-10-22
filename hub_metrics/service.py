"""Coordinate domain operations for HTTP request metrics."""

from hub_metrics.entity import Metric
from hub_metrics.hub_metrics import IService


class Service(IService):
    def __init__(self, repository):
        """Bind the HTTP metrics repository."""
        self.repository = repository

    def add_metric(self, metric: Metric) -> Metric:
        """Store a metric through the repository and return the stored entity."""
        try:
            return self.repository.create_metric(metric)
        except Exception as e:
            raise RuntimeError(f"Error adding metric: {e}")

    def get_all_metrics(self) -> list[Metric]:
        """Retrieve all stored metrics."""
        try:
            return self.repository.get_all_metrics()
        except Exception as e:
            raise RuntimeError(f"Error retrieving metrics: {e}")
