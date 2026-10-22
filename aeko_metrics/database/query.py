"""Build MongoDB filters and documents for SDK run metrics."""

from datetime import datetime

from aeko_metrics.entity import Metric


def create_metric_query(metric: Metric) -> dict:
    """Build a run metric document with a request reference and ordered agent invocations."""

    return {
        "id_request": metric.id_request,
        "latency": metric.latency,
        "error_description": metric.error_description,
        "flow": metric.flow,
        "cost_usd": metric.cost_usd,
        "id_external_user": metric.id_external_user,
        "id_external_company": metric.id_external_company,
        "created_at": metric.created_at or datetime.utcnow(),
        "used_agents": [
            {
                "name": agent.name,
                "input_tokens": agent.input_tokens,
                "output_tokens": agent.output_tokens,
                "llm": agent.llm,
                "used_tools": list(agent.used_tools),
            }
            for agent in metric.used_agents
        ],
    }


def get_all_metrics_query() -> tuple[dict, dict]:
    """Return a filter and projection that include all metric documents and fields."""
    return {}, {}


def get_company_cost_query(
    id_external_company: int, since: datetime
) -> tuple[dict, dict]:
    """Build the filter and projection for company costs at or after the supplied time."""
    return (
        {"id_external_company": id_external_company, "created_at": {"$gte": since}},
        {"id_external_user": 1, "cost_usd": 1},
    )
