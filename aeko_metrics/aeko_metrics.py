"""Define service and repository contracts for SDK run metrics."""

from abc import ABC, abstractmethod
from datetime import datetime

from aeko_metrics.entity import CompanyCost, Metric


class IRepository(ABC):
    @abstractmethod
    def create_metric(self, metric: Metric) -> Metric:
        """Persist a metric and return it with its database identifier."""
        pass

    @abstractmethod
    def get_all_metrics(self) -> list[Metric]:
        """Retrieve all stored metrics."""
        pass

    @abstractmethod
    def get_company_metrics(
        self, id_external_company: int, since: datetime
    ) -> list[Metric]:
        """Retrieve metrics for one company at or after the supplied time."""
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

    @abstractmethod
    def company_cost(self, n: int, id_external_company: int) -> CompanyCost:
        """Sum USD cost for a company over the trailing n days, grouped by user."""
        pass
