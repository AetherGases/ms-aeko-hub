"""Map SDK run metrics to persisted aeko_metrics entities."""

from __future__ import annotations

from aeko_metrics.constants import MEMORY_WORKER_ID_REQUEST
from aeko_metrics.cost import cost_usd
from aeko_metrics.entity import AgentMetric, Metric as AekoMetric
from aeko_metrics.prices import load_prices
from internal.shared.event_tracking import (
    current_metric_id_external_company,
    current_metric_id_external_user,
)


def agents_from_sdk(metrics) -> list[AgentMetric]:
    """Map SDK agent usage rows onto persisted aeko_metrics agent entities."""
    return [
        AgentMetric(
            name=agent.name,
            input_tokens=agent.input_tokens,
            output_tokens=agent.output_tokens,
            llm=agent.llm,
            used_tools=list(agent.used_tools),
        )
        for agent in metrics.used_agents
    ]


def _valid_company_id(id_external_company: int | None) -> bool:
    """Return whether the company identifier is a positive integer."""
    return (
        not isinstance(id_external_company, bool)
        and isinstance(id_external_company, int)
        and id_external_company > 0
    )


def metric_from_sdk_run(metrics) -> AekoMetric:
    """Build a domain metric with USD cost resolved from token usage."""
    agents = agents_from_sdk(metrics)
    prices = load_prices()
    id_external_user = current_metric_id_external_user()
    id_external_company = current_metric_id_external_company()
    if metrics.id_request != MEMORY_WORKER_ID_REQUEST and not _valid_company_id(
        id_external_company
    ):
        raise ValueError(
            "id_external_company is required for aeko_metrics outside the memory worker"
        )
    return AekoMetric(
        id_request=metrics.id_request,
        latency=metrics.latency,
        error_description=metrics.error_description,
        flow=metrics.flow,
        cost_usd=cost_usd(agents, prices),
        used_agents=agents,
        id_external_user=id_external_user,
        id_external_company=id_external_company,
    )
