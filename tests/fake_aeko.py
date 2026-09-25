"""Provide a scripted Aeko SDK double for configuration, chat, and analysis tests.

Calls retain request identifiers and record agent metrics. Failed reviews
raise with metrics attached and do not append a conversation message.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal, Sequence

from pydantic import BaseModel, ConfigDict, Field, ValidationError

__version__ = "3.5.0"


AGENT_NAMES: tuple[str, ...] = (
    "Roteador",
    "FAQ",
    "Orquestrador",
    "Guardrail de Saída",

    "Verificador de Resposta",
    "Análista de inventários",
    "Analista de Poluentes",
    "Analista de Gases Verdes",
    "Coordenador de Melhoria Contínua",
)

DEFAULT_FAST_MODEL = "gemini-3.1-flash-lite"
DEFAULT_SLOW_MODEL = "gemini-3.5-flash"
DEFAULT_MAX_TOKENS = 1024
DEFAULT_REPORT_MAX_TOKENS = 8192


DEFAULT_LATENCY = 12


def _now() -> datetime:
    return datetime.now(timezone.utc)


CONVERSATIONAL_FLOW = "conversational"
ANALYTICAL_FLOW = "analytical"


REVIEW_FAILURE = "no answer approved by the output guardrail or the response checker"


class AekoAgentMetrics(BaseModel):
    """What one agent *invocation* consumed — one entry per call, not per agent."""

    name: str
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    llm: str = ""
    used_tools: list[str] = Field(default_factory=list)


class AekoMetrics(BaseModel):
    """Metrics for one scripted SDK run, retaining the caller's request identifier."""

    id_request: str
    latency: int = Field(default=0, ge=0)
    error_description: str | None = None
    flow: str
    used_agents: list[AekoAgentMetrics] = Field(default_factory=list)


class AekoError(Exception):
    """Base SDK error carrying optional run metrics."""

    aeko_metrics: AekoMetrics | None = None


class AekoNotConfiguredError(AekoError):
    """Raised when the SDK is used before `Aeko.config()` supplies an API key."""


class MalformedAgentOutputError(AekoError):
    """Raised when an agent's answer does not match the shape its prompt demands."""


class UnknownAgentError(AekoError):
    """Raised when tools are registered for an agent name that doesn't exist."""

    def __init__(self, agent: str, known_agents: tuple[str, ...]):
        self.agent = agent
        self.known_agents = known_agents
        super().__init__(
            f"'{agent}' is not a known agent. Valid names: {', '.join(known_agents)}."
        )


@dataclass(frozen=True)
class AekoTool:
    tool: Any
    description: str = ""

    @property
    def name(self) -> str:
        """Return the wrapped tool name."""
        return getattr(self.tool, "name", type(self.tool).__name__)

    def to_prompt_line(self) -> str:
        """Format the wrapped tool name and description for an agent prompt."""
        description = self.description or getattr(self.tool, "description", "")
        return f"{self.name} - {description}".rstrip(" -")

    @classmethod
    def wrap(cls, tool: "AekoTool | Any") -> "AekoTool":
        """Wrap a tool in the SDK tool representation."""
        return tool if isinstance(tool, cls) else cls(tool=tool)


class AekoUser(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str | None = Field(default=None, alias="_id")
    id_external_user: int
    role: str
    usecase: str = ""


class AekoUserMemory(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str | None = Field(default=None, alias="_id")
    id_user: str | None = None
    field: str
    description: str
    created_at: datetime | None = None
    expires_at: datetime | None = None

    def to_prompt_line(self) -> str:
        """Format the wrapped tool name and description for an agent prompt."""
        return f"{self.field}: {self.description}"


class AekoMessage(BaseModel):
    """One exchanged conversation turn with its submission timestamp."""

    input: str
    output: str = ""
    submitted_at: datetime = Field(default_factory=_now)


class AekoSession(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str | None = Field(default=None, alias="_id")
    id_user: str | None = None
    name: str = ""
    messages: list[AekoMessage] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class AekoMessageResponse(BaseModel):
    message: AekoMessage
    aeko_metrics: AekoMetrics
    id_session: str | None = None
    id_user: str | None = None
    agents_called: list[str] = Field(default_factory=list)
    approved: bool = False
    guardrail_retries: int = Field(default=0, ge=0)


class AekoSummaryResponse(BaseModel):
    """What `generate_summary()` hands back: the summary text and what it cost."""

    summary: str
    aeko_metrics: AekoMetrics


class AekoImprovementPlan(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str | None = Field(default=None, alias="_id")
    id_external_inventory: int
    defined_problem: str
    method: str
    reasoning: str
    updated_at: datetime = Field(default_factory=_now)


class AekoCatalogItem(BaseModel):
    id: int
    name: str


class AekoCategoryCatalogItem(BaseModel):
    id: int
    name: str
    classification: Literal["UPSTREAM", "DOWNSTREAM"] | None = None


class AekoInventoryEmission(BaseModel):
    quantity_co2e: float
    methodology_description: str | None = None
    supplier_data_percentage: float | None = None
    gas: int | None = None
    scope: int | None = None
    category: int | None = None
    is_upstream: bool | None = None
    is_reduction: bool


class AekoExtractedInventory(BaseModel):
    description: str | None = None
    start_period: str | None = None
    end_period: str | None = None
    emissions: list[AekoInventoryEmission] = Field(default_factory=list)


class AekoAnalysisResponse(BaseModel):
    """What `analyze()` hands back: the plan, the structured inventory, and what it cost."""

    plan: AekoImprovementPlan
    inventory: AekoExtractedInventory
    aeko_metrics: AekoMetrics


class _Runtime:
    def __init__(self):
        self.reset()

    def reset(self):
        """Restore the simulated SDK runtime defaults."""
        self.api_key = None
        self.fast_model = DEFAULT_FAST_MODEL
        self.slow_model = DEFAULT_SLOW_MODEL
        self.max_tokens = DEFAULT_MAX_TOKENS
        self.report_max_tokens = DEFAULT_REPORT_MAX_TOKENS
        self.tools = {}
        self.config_calls = []
        self.set_tools_calls = []

    def require_api_key(self):
        """Raise when the simulated SDK has not been configured."""
        if not self.api_key:
            raise AekoNotConfiguredError(
                "Aeko is not configured. Call Aeko.config() with a Gemini API key."
            )
        return self.api_key


RUNTIME = _Runtime()


class Aeko:
    """Configuration facade. Nothing here reads the environment."""

    @staticmethod
    def config(api_key: str, *, fast_model: str | None = None, slow_model: str | None = None,
               max_tokens: int | None = None, report_max_tokens: int | None = None,
               temperature: float | None = None, top_p: float | None = None,
               top_k: int | None = None) -> None:
        """Configure the simulated SDK runtime from the supplied settings."""
        if not api_key or not isinstance(api_key, str):
            raise AekoNotConfiguredError("Aeko.config() requires a non-empty API key.")

        RUNTIME.config_calls.append(
            {
                "api_key": api_key,
                "fast_model": fast_model,
                "slow_model": slow_model,
                "max_tokens": max_tokens,
                "report_max_tokens": report_max_tokens,
                "temperature": temperature,
                "top_p": top_p,
                "top_k": top_k,
            }
        )

        RUNTIME.api_key = api_key
        if fast_model is not None:
            RUNTIME.fast_model = fast_model
        if slow_model is not None:
            RUNTIME.slow_model = slow_model
        if max_tokens is not None:
            RUNTIME.max_tokens = max_tokens
        if report_max_tokens is not None:
            RUNTIME.report_max_tokens = report_max_tokens

    @staticmethod
    def is_configured() -> bool:
        """Return whether the simulated SDK has an API key."""
        return bool(RUNTIME.api_key)

    @staticmethod
    def reset() -> None:
        """Restore the simulated SDK runtime defaults."""
        RUNTIME.reset()
        AekoMessenger.reset_script()
        AekoInventoryAnalyzer.reset_script()


def _tracking(id_request, flow, agents, error_description=None, latency=None):
    """The `AekoMetrics` a scripted run reports."""

    return AekoMetrics(
        id_request=id_request,
        latency=DEFAULT_LATENCY if latency is None else latency,
        error_description=error_description,
        flow=flow,
        used_agents=[
            AekoAgentMetrics(
                name=name,
                input_tokens=11,
                output_tokens=22,
                llm="fake-fast",
                used_tools=[],
            )
            for name in agents
        ],
    )


def _fail_with(error, metrics):
    """Attach a failed run's tracking to the exception carrying it out."""

    try:
        setattr(error, "aeko_metrics", metrics)
    except AttributeError:
        pass

    return error


class AekoMessenger:
    """Conversational entry point, scripted instead of routed through Gemini."""

    instances: list["AekoMessenger"] = []

    next_output: str | None = None
    next_approved: bool = True
    next_agents: tuple[str, ...] = ("FAQ",)
    next_guardrail_retries: int = 0
    next_error: Exception | None = None
    next_latency: int | None = None
    next_summary: str | None = None
    next_summary_error: Exception | None = None
    next_summary_agents: tuple[str, ...] = ("FAQ",)

    def __init__(self, user: AekoUser, memories: Sequence[AekoUserMemory] | None = None):
        if not isinstance(user, AekoUser):
            raise TypeError(f"AekoMessenger takes an AekoUser, got {type(user).__name__}.")

        memories = list(memories or [])
        for memory in memories:
            if not isinstance(memory, AekoUserMemory):
                raise TypeError(
                    f"AekoMessenger takes AekoUserMemory objects, got {type(memory).__name__}."
                )

        self.user = user
        self.memories = memories
        self.sent = []
        AekoMessenger.instances.append(self)

    @classmethod
    def reset_script(cls):
        """Clear scripted responses, errors, and recorded calls."""
        cls.instances = []
        cls.next_output = None
        cls.next_approved = True
        cls.next_agents = ("FAQ",)
        cls.next_guardrail_retries = 0
        cls.next_error = None
        cls.next_latency = None
        cls.next_summary = None
        cls.next_summary_error = None
        cls.next_summary_agents = ("FAQ",)

    @classmethod
    def set_tools(cls, tools: dict[str, list[Any]]) -> None:
        """Register tools for the supplied agent names in the simulated SDK."""
        normalized = {}
        for agent, agent_tools in tools.items():
            if agent not in AGENT_NAMES:
                raise UnknownAgentError(agent, AGENT_NAMES)
            normalized[agent] = [AekoTool.wrap(tool) for tool in agent_tools]

        RUNTIME.set_tools_calls.append(dict(tools))
        RUNTIME.tools = normalized

    def send_message(self, message: str, session: AekoSession, *,
                     id_request: str) -> AekoMessageResponse:
        """Record the conversation call and return or raise its scripted result."""
        RUNTIME.require_api_key()

        if not isinstance(session, AekoSession):
            raise TypeError(
                f"send_message() takes an AekoSession, got {type(session).__name__}."
            )

        if not isinstance(id_request, str):
            raise TypeError(
                f"send_message() takes id_request as a string, got {type(id_request).__name__}."
            )

        self.sent.append((message, session, id_request))

        if type(self).next_error is not None:
            error = type(self).next_error
            raise _fail_with(
                error,
                _tracking(
                    id_request,
                    CONVERSATIONAL_FLOW,
                    type(self).next_agents,
                    f"{type(error).__name__}: {error}",
                    type(self).next_latency,
                ),
            )

        output = type(self).next_output
        if output is None:
            output = f"echo: {message}" if type(self).next_approved else ""

        if not output:
            raise _fail_with(
                MalformedAgentOutputError(REVIEW_FAILURE),
                _tracking(
                    id_request,
                    CONVERSATIONAL_FLOW,
                    type(self).next_agents,
                    REVIEW_FAILURE,
                    type(self).next_latency,
                ),
            )

        turn = AekoMessage(input=message, output=output)

        session.messages.append(turn)
        session.updated_at = turn.submitted_at

        return AekoMessageResponse(
            message=turn,
            aeko_metrics=_tracking(
                id_request,
                CONVERSATIONAL_FLOW,
                type(self).next_agents,
                None,
                type(self).next_latency,
            ),
            id_session=session.id,
            id_user=session.id_user,
            agents_called=list(type(self).next_agents),

            approved=True,
            guardrail_retries=type(self).next_guardrail_retries,
        )

    def generate_summary(self, messages: Sequence[AekoMessage], *,
                         id_request: str) -> AekoSummaryResponse:
        """Record the summary call and return or raise its scripted result."""
        RUNTIME.require_api_key()

        if not isinstance(id_request, str):
            raise TypeError(
                f"generate_summary() takes id_request as a string, got {type(id_request).__name__}."
            )

        for message in messages:
            if not isinstance(message, AekoMessage):
                raise TypeError(
                    f"generate_summary() takes AekoMessage objects, got {type(message).__name__}."
                )

        if type(self).next_summary_error is not None:
            error = type(self).next_summary_error
            raise _fail_with(
                error,
                _tracking(
                    id_request,
                    CONVERSATIONAL_FLOW,
                    type(self).next_summary_agents,
                    f"{type(error).__name__}: {error}",
                    type(self).next_latency,
                ),
            )

        summary = type(self).next_summary
        if summary is None:
            summary = " ".join(message.input for message in messages)

        return AekoSummaryResponse(
            summary=summary,
            aeko_metrics=_tracking(
                id_request,
                CONVERSATIONAL_FLOW,
                type(self).next_summary_agents,
                None,
                type(self).next_latency,
            ),
        )


DEFAULT_EXTRACTED_INVENTORY = {
    "description": "Boiler-dominated inventory",
    "start_period": "2025-01-01",
    "end_period": "2025-12-31",
    "emissions": [
        {
            "quantity_co2e": 12400.0,
            "methodology_description": "stationary combustion",
            "supplier_data_percentage": None,
            "gas": 1,
            "scope": 1,
            "category": None,
            "is_upstream": None,
            "is_reduction": False,
        }
    ],
}


def _catalog_items(name: str, items, model):
    """Validate a catalog list and reject duplicate identifiers before analysis."""
    try:
        parsed = [model.model_validate(item) for item in items]
    except (ValidationError, TypeError, ValueError) as exc:
        raise ValueError(f"{name} is not a valid Aeko catalog.") from exc

    identifiers = [item.id for item in parsed]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError(f"{name} contains duplicate ids.")
    return parsed


class AekoInventoryAnalyzer:
    """Report entry point, scripted instead of routed through Gemini."""

    instances: list["AekoInventoryAnalyzer"] = []

    next_plan_fields: dict[str, str] = {}
    next_inventory_fields: dict[str, Any] = {}
    next_error: Exception | None = None
    next_agents: tuple[str, ...] = ("Análista de inventários",)
    next_latency: int | None = None

    def __init__(self):
        self.context = ""
        self.analyzed = []
        AekoInventoryAnalyzer.instances.append(self)

    @classmethod
    def reset_script(cls):
        """Clear scripted responses, errors, and recorded calls."""
        cls.instances = []
        cls.next_plan_fields = {}
        cls.next_inventory_fields = {}
        cls.next_error = None
        cls.next_agents = ("Análista de inventários",)
        cls.next_latency = None

    def set_context(self, context: str) -> None:
        """Record the analysis context supplied by the service."""
        if not isinstance(context, str):
            raise TypeError(f"set_context() takes a string, got {type(context).__name__}.")
        self.context = context or ""

    def analyze(self, inventory: str, *, id_external_inventory: int,
                id_request: str, gases, scopes, categories) -> AekoAnalysisResponse:
        """Record the inventory analysis call and return or raise its scripted result."""
        RUNTIME.require_api_key()

        if not isinstance(inventory, str):
            raise TypeError(
                f"analyze() takes the inventory as Markdown text, got {type(inventory).__name__}."
            )
        if not isinstance(id_external_inventory, int):
            raise TypeError(
                "analyze() takes id_external_inventory as an int, "
                f"got {type(id_external_inventory).__name__}."
            )
        if not isinstance(id_request, str):
            raise TypeError(
                f"analyze() takes id_request as a string, got {type(id_request).__name__}."
            )

        gases = _catalog_items("gases", gases, AekoCatalogItem)
        scopes = _catalog_items("scopes", scopes, AekoCatalogItem)
        categories = _catalog_items("categories", categories, AekoCategoryCatalogItem)

        self.analyzed.append((inventory, id_external_inventory, id_request, gases, scopes, categories))

        if type(self).next_error is not None:
            error = type(self).next_error
            raise _fail_with(
                error,
                _tracking(
                    id_request,
                    ANALYTICAL_FLOW,
                    type(self).next_agents,
                    f"{type(error).__name__}: {error}",
                    type(self).next_latency,
                ),
            )

        fields = {
            "defined_problem": "high scope 1 emissions",
            "method": "replace the boiler fleet",
            "reasoning": "direct combustion dominates the inventory",
            **type(self).next_plan_fields,
        }

        inventory_fields = {
            **DEFAULT_EXTRACTED_INVENTORY,
            **type(self).next_inventory_fields,
        }

        return AekoAnalysisResponse(
            plan=AekoImprovementPlan(id_external_inventory=id_external_inventory, **fields),
            inventory=AekoExtractedInventory.model_validate(inventory_fields),
            aeko_metrics=_tracking(
                id_request,
                ANALYTICAL_FLOW,
                type(self).next_agents,
                None,
                type(self).next_latency,
            ),
        )
