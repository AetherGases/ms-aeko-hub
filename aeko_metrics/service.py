"""Coordinate domain operations for SDK run metrics."""

from datetime import datetime, timedelta

from aeko_metrics.aeko_metrics import IService
from aeko_metrics.entity import CompanyCost, Metric, UserCost


class Service(IService):
    def __init__(self, repository):
        """Bind the metrics repository."""
        self.repository = repository

    def add_metric(self, metric: Metric) -> Metric:
        """Store a metric through the repository and return the stored entity."""
        try:
            return self.repository.create_metric(metric)
        except Exception as e:
            raise RuntimeError(f"Error adding aeko metric: {e}")

    def get_all_metrics(self) -> list[Metric]:
        """Retrieve all stored metrics."""
        try:
            return self.repository.get_all_metrics()
        except Exception as e:
            raise RuntimeError(f"Error retrieving aeko metrics: {e}")

    def company_cost(self, n: int, id_external_company: int) -> CompanyCost:
        """Sum USD cost for a company over the trailing n days, grouped by user."""
        if isinstance(n, bool) or not isinstance(n, int) or n <= 0:
            raise ValueError("n must be a positive integer.")
        if (
            isinstance(id_external_company, bool)
            or not isinstance(id_external_company, int)
            or id_external_company <= 0
        ):
            raise ValueError("id_external_company must be a positive integer.")
        try:
            metrics = self.repository.get_company_metrics(
                id_external_company, datetime.utcnow() - timedelta(days=n)
            )
        except Exception as e:
            raise RuntimeError(f"Error retrieving company cost: {e}")
        totals: dict[int, float] = {}
        for metric in metrics:
            user = metric.id_external_user
            if user is None:
                continue
            totals[user] = totals.get(user, 0.0) + metric.cost_usd
        users = [
            UserCost(id_external_user=user, cost_usd=round(cost, 6))
            for user, cost in sorted(totals.items())
        ]
        return CompanyCost(
            id_external_company=id_external_company,
            cost_usd=round(sum(user.cost_usd for user in users), 6),
            users=users,
        )
