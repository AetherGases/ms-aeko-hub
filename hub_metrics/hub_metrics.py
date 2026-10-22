"""Define service and repository contracts for HTTP request metrics."""

from abc import ABC, abstractmethod

from hub_metrics.entity import Metric


class IRepository(ABC):
    @abstractmethod
    def create_metric(self, metric: Metric) -> Metric:
        """Persist a metric and return it with its database identifier."""
        pass

    @abstractmethod
    def get_all_metrics(self) -> list[Metric]:
        """Retrieve all stored metrics."""
        pass


class IService(ABC):
    @abstractmethod
    def add_metric(self, metric: Metric) -> Metric:
        """Store a metric through the repository and return the stored entity."""
        pass

    @abstractmethod
    def get_all_metrics(self) -> list[Metric]:
        """Retrieve all stored metrics."""
        pass
