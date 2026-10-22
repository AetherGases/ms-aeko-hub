"""Persist and retrieve SDK run metrics through MongoDB."""

from aeko_metrics.aeko_metrics import IRepository
from aeko_metrics.constants import COLLECTION
from aeko_metrics.database import query as q
from aeko_metrics.entity import AgentMetric, Metric
from internal.shared import Module, logged


class Repository(IRepository):
    def __init__(self, db):
        """Bind the MongoDB database handle."""
        self.db = db

    @logged(Module.DATABASE, "aeko_metrics.create_metric")
    def create_metric(self, metric: Metric) -> Metric:
        """Persist a metric and return it with its database identifier."""
        try:
            result = self.db[COLLECTION].insert_one(q.create_metric_query(metric))
            metric.id = str(result.inserted_id)
            return metric
        except Exception as e:
            raise RuntimeError(f"Error creating aeko metric in database: {e}")

    @logged(Module.DATABASE, "aeko_metrics.get_all_metrics")
    def get_all_metrics(self) -> list[Metric]:
        """Retrieve all stored metrics."""
        try:
            query, projection = q.get_all_metrics_query()
            return [
                metric_from_data(data)
                for data in self.db[COLLECTION].find(query, projection)
            ]
        except Exception as e:
            raise RuntimeError(f"Error fetching aeko metrics from database: {e}")

    @logged(Module.DATABASE, "aeko_metrics.get_company_metrics")
    def get_company_metrics(self, id_external_company: int, since) -> list[Metric]:
        """Retrieve metrics for one company at or after the supplied time."""
        try:
            query, projection = q.get_company_cost_query(id_external_company, since)
            return [
                metric_from_data(data)
                for data in self.db[COLLECTION].find(query, projection)
            ]
        except Exception as e:
            raise RuntimeError(
                f"Error fetching company aeko metrics from database: {e}"
            )


def agent_metric_from_data(data: dict) -> AgentMetric:
    """Map stored agent invocation data to an agent metric entity."""
    return AgentMetric(
        name=data.get("name", ""),
        input_tokens=data.get("input_tokens", 0),
        output_tokens=data.get("output_tokens", 0),
        llm=data.get("llm", ""),
        used_tools=data.get("used_tools", []),
    )


def metric_from_data(data: dict) -> Metric:
    """Map a stored document to a metric, using defaults for missing optional fields."""
    return Metric(
        id=str(data.get("_id")) if data.get("_id") is not None else None,
        id_request=data.get("id_request", ""),
        latency=data.get("latency", 0),
        error_description=data.get("error_description"),
        flow=data.get("flow", ""),
        cost_usd=data.get("cost_usd", 0.0),
        id_external_user=data.get("id_external_user"),
        id_external_company=data.get("id_external_company"),
        created_at=data.get("created_at"),
        used_agents=[
            agent_metric_from_data(agent) for agent in data.get("used_agents", [])
        ],
    )
