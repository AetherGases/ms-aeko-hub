"""Define the domain entities for SDK run metrics."""

from datetime import datetime


class AgentMetric:
    """What one agent *invocation* of a run consumed."""

    name: str
    input_tokens: int
    output_tokens: int
    llm: str
    used_tools: list[str]

    def __init__(
        self,
        name: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        llm: str = "",
        used_tools: list[str] | None = None,
    ):
        """Store token, model, and tool usage for one agent invocation."""
        self.name = name
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.llm = llm
        self.used_tools = list(used_tools or [])


class Metric:
    """One SDK run, as the observability dashboard needs it."""

    id: str | None
    id_request: str
    latency: int
    error_description: str | None
    flow: str
    cost_usd: float
    used_agents: list[AgentMetric]
    id_external_user: int | None
    id_external_company: int | None
    created_at: datetime | None

    def __init__(
        self,
        id_request: str,
        latency: int,
        flow: str,
        used_agents: list[AgentMetric] | None = None,
        error_description: str | None = None,
        id: str | None = None,
        cost_usd: float = 0.0,
        id_external_user: int | None = None,
        id_external_company: int | None = None,
        created_at: datetime | None = None,
    ):
        """Store the fields of one SDK run metric."""
        self.id = id
        self.id_request = id_request
        self.latency = latency
        self.error_description = error_description
        self.flow = flow
        self.cost_usd = cost_usd
        self.used_agents = list(used_agents or [])
        self.id_external_user = id_external_user
        self.id_external_company = id_external_company
        self.created_at = created_at


class UserCost:
    """USD spent by one external user inside a company window."""

    id_external_user: int
    cost_usd: float

    def __init__(self, id_external_user: int, cost_usd: float):
        """Store the USD cost attributed to one external user."""
        self.id_external_user = id_external_user
        self.cost_usd = cost_usd


class CompanyCost:
    """USD spent by a company's users inside a trailing window."""

    id_external_company: int
    cost_usd: float
    users: list[UserCost]

    def __init__(
        self,
        id_external_company: int,
        cost_usd: float,
        users: list[UserCost] | None = None,
    ):
        """Store company cost totals and per-user breakdowns."""
        self.id_external_company = id_external_company
        self.cost_usd = cost_usd
        self.users = list(users or [])
