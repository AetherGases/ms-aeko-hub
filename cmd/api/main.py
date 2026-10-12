"""Compose the FastAPI application, domain services, and Aeko SDK adapters.

This is the only module that imports the SDK. Configuration is captured after
loading the environment; the application lifespan initializes the database,
cache, agent tools, and metric sinks and closes database, cache, and MCP connections.
"""

from contextlib import asynccontextmanager
import os
import threading

from dotenv import load_dotenv
from fastapi import FastAPI
from pymongo import MongoClient
from redis import Redis

from cmd.api.integrations.a2a.service import Service as A2AService
from cmd.api.acl.mcp_auth import wrap_mcp_auth
from cmd.api.acl.open_ai.server import build_mcp_server
from cmd.api.integrations.climatiq_api import get_climatiq_tools
from cmd.api.integrations.inventory_api import create_inventory
from cmd.api.integrations.mcp.chroma_mcp import (
    CHROMA_SESSION,
    configure as configure_chroma_tools,
    get_gases_info_tools,
    get_improvement_plan_problem_tools,
)
from cmd.api.tools.ask_aeko import configure as configure_ask_aeko
from cmd.api.tools.inventory_tools import configure as configure_inventory_tools
from cmd.api.tools.mongo_tools import (
    configure as configure_mongo_tools,
    get_improvement_plan_tools,
    get_user_memory_tools,
    get_session_tools,
)
from cmd.api.integrations.tavily_api import (
    get_tavily_search_tools,
    get_tavily_site_map_tool,
)
from cmd.api.tools.calculator import get_calculator_tools
from cmd.api.tools.finance import get_roi_payback_tools
from aeko_metrics.database.repository import Repository as AekoMetricsRepository
from aeko_metrics.metric_sink import metric_from_sdk_run
from aeko_metrics.service import Service as AekoMetricsService
from hub_metrics.database.repository import Repository as HubMetricsRepository
from hub_metrics.entity import Metric
from hub_metrics.service import Service as HubMetricsService
from cmd.memory_generator_worker.constants import REDIS_SCAN_COUNT, SESSION_INACTIVITY_MINUTES
from improvement_plan.database.repository import Repository as ImprovementPlanRepository
from improvement_plan.improvement_plan import MalformedPlanError
from improvement_plan.service import Service as ImprovementPlanService
from internal.observability.telemetry import (
    configure as configure_opentelemetry,
    record_aeko_run,
    record_hub_metric,
    shutdown as shutdown_opentelemetry,
)
from internal.http.improvement_plan_handlers import router as improvement_plan_router
from internal.http.oauth_handlers import router as oauth_router
from internal.http.session_handlers import router as session_router
from internal.http.upload_ticket_handlers import router as upload_ticket_router
from internal.http.user_handlers import router as user_router
from oauth.cache.repository import Repository as OAuthCodeRepository
from oauth.service import Service as OAuthService
from internal.shared import (
    Event,
    Module,
    RequestLogMiddleware,
    log_failure,
    operation,
    set_aeko_metrics_sink,
    set_event_sink,
    silence_uvicorn_access_log,
)
from session.cache.repository import Repository as SessionCacheRepository
from session.database.repository import Repository as SessionRepository
from session.service import Service as SessionService
from session.session import GuardrailRejectedError
from upload_ticket.cache.repository import Repository as UploadTicketRepository
from upload_ticket.service import Service as UploadTicketService
from user.database.repository import Repository as UserRepository
from user.service import Service as UserService


from aeko import (
    Aeko,
    AekoInventoryAnalyzer,
    AekoMessage,
    AekoMessenger,
    AekoSession,
    AekoTool,
    AekoUser,
    AekoUserMemory,
    MalformedAgentOutputError,
)

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = os.getenv("DB_NAME")
REDIS_URI = os.getenv("REDIS_URI")


GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
AEKO_FAST_MODEL = os.getenv("AEKO_FAST_MODEL")
AEKO_SLOW_MODEL = os.getenv("AEKO_SLOW_MODEL")
AEKO_MAX_TOKENS = os.getenv("AEKO_MAX_TOKENS")
AEKO_REPORT_MAX_TOKENS = os.getenv("AEKO_REPORT_MAX_TOKENS")
AEKO_TEMPERATURE = os.getenv("AEKO_TEMPERATURE")
AEKO_TOP_P = os.getenv("AEKO_TOP_P")
AEKO_TOP_K = os.getenv("AEKO_TOP_K")


TAVILY_SITE_MAP_TOOLS = [AekoTool(tool=tool) for tool in get_tavily_site_map_tool()]
TAVILY_RESEARCH_TOOLS = [AekoTool(tool=tool) for tool in get_tavily_search_tools()]


IMPROVEMENT_PLAN_TOOLS = [AekoTool(tool=tool) for tool in get_improvement_plan_tools()] + [
    AekoTool(tool=tool) for tool in get_improvement_plan_problem_tools()
]
USER_MEMORY_TOOLS = [AekoTool(tool=tool) for tool in get_user_memory_tools()]
SESSION_TOOLS = [AekoTool(tool=tool) for tool in get_session_tools()]


GASES_INFO_TOOLS = [AekoTool(tool=tool) for tool in get_gases_info_tools()]


CLIMATIQ_TOOLS = [AekoTool(tool=tool) for tool in get_climatiq_tools()]


CALCULATOR_TOOLS = [AekoTool(tool=tool) for tool in get_calculator_tools()]


ROI_PAYBACK_TOOLS = [AekoTool(tool=tool) for tool in get_roi_payback_tools()]


AEKO_TOOLS = {

    "FAQ": list(TAVILY_SITE_MAP_TOOLS)
    + list(TAVILY_RESEARCH_TOOLS)
    + list(USER_MEMORY_TOOLS)
    + list(SESSION_TOOLS)
    + list(CALCULATOR_TOOLS),
    "Análista de inventários": list(IMPROVEMENT_PLAN_TOOLS)
    + list(USER_MEMORY_TOOLS)
    + list(SESSION_TOOLS)
    + list(CALCULATOR_TOOLS),

    "Analista de Poluentes": list(TAVILY_RESEARCH_TOOLS)
    + list(IMPROVEMENT_PLAN_TOOLS)
    + list(USER_MEMORY_TOOLS)
    + list(SESSION_TOOLS)
    + list(CLIMATIQ_TOOLS)
    + list(CALCULATOR_TOOLS),

    "Analista de Gases Verdes": list(TAVILY_RESEARCH_TOOLS)
    + list(IMPROVEMENT_PLAN_TOOLS)
    + list(USER_MEMORY_TOOLS)
    + list(SESSION_TOOLS)
    + list(GASES_INFO_TOOLS)
    + list(CALCULATOR_TOOLS),

    "Coordenador de Melhoria Contínua": list(TAVILY_RESEARCH_TOOLS)
    + list(IMPROVEMENT_PLAN_TOOLS)
    + list(USER_MEMORY_TOOLS)
    + list(SESSION_TOOLS)
    + list(CALCULATOR_TOOLS)
    + list(ROI_PAYBACK_TOOLS),
}


MCP_SESSIONS = (CHROMA_SESSION,)

CHATGPT_MCP_PREFIX = "/ai/mcp"

chatgpt_mcp = build_mcp_server()
chatgpt_mcp_app = wrap_mcp_auth(chatgpt_mcp.streamable_http_app())


MCP_WARM_UP = os.getenv("AEKO_MCP_WARM_UP", "true")

mongo_client = None
redis_client = None
db = None


def _int_or_none(value: str | None) -> int | None:
    return int(value) if value else None


def _float_or_none(value: str | None) -> float | None:
    return float(value) if value else None


def _warm_up_mcp_sessions() -> None:
    """Start each MCP session in a background thread without delaying API startup."""

    def warm_up(session) -> None:
        """Start an MCP session and log a failed warm-up without stopping the API."""
        try:
            session.start()
        except Exception as exc:
            log_failure(
                Module.MCP,
                f"{session.name}.warm_up gave up: {type(exc).__name__}: {exc}",
            )

    for session in MCP_SESSIONS:
        threading.Thread(target=warm_up, args=(session,), daemon=True).start()


def _carrying_tracking(error: Exception, cause: MalformedAgentOutputError) -> Exception:
    """Copy SDK run metrics to the translated domain exception."""

    error.aeko_metrics = getattr(cause, "aeko_metrics", None)
    return error


class _Messenger(AekoMessenger):
    """Adapt SDK conversation errors to domain errors while retaining run metrics."""

    def send_message(self, message, session, *, id_request):
        """Send a conversation turn and translate SDK review errors while retaining metrics."""
        try:
            return super().send_message(message, session, id_request=id_request)
        except MalformedAgentOutputError as exc:
            raise _carrying_tracking(
                GuardrailRejectedError(
                    "No answer for this turn was approved by the output guardrail "
                    "or the response checker. Please rephrase."
                ),
                exc,
            ) from exc


class _InventoryAnalyzer(AekoInventoryAnalyzer):
    """Adapt SDK analysis errors to domain errors while retaining run metrics."""

    def analyze(self, inventory, *, id_external_inventory, id_request, gases, scopes, categories):
        """Analyze an inventory and translate malformed SDK output to a domain error."""
        try:
            return super().analyze(
                inventory,
                id_external_inventory=id_external_inventory,
                id_request=id_request,
                gases=gases,
                scopes=scopes,
                categories=categories,
            )
        except MalformedAgentOutputError as exc:
            raise _carrying_tracking(
                MalformedPlanError(
                    "The analysis produced no plan in the shape a report is stored in."
                ),
                exc,
            ) from exc


def build_messenger(user, memories) -> AekoMessenger:
    """Build a request-specific SDK messenger from the user and valid memories."""
    return _Messenger(
        AekoUser(
            id=user.id,
            id_external_user=user.id_external_user,
            role=user.role,
            usecase=user.usecase,
        ),
        [
            AekoUserMemory(
                id=memory.id,
                id_user=memory.id_user,
                field=memory.field,
                description=memory.description,
                created_at=memory.created_at,
                expires_at=memory.expires_at,
            )
            for memory in memories
        ],
    )


def build_session(session) -> AekoSession:
    """Convert a domain session and its messages to the SDK session representation."""
    return AekoSession(
        id=session.id,
        id_user=session.id_user,
        name=session.name,
        messages=[
            AekoMessage(
                input=message.input,
                output=message.output,
                submitted_at=message.submitted_at,
            )
            for message in session.messages
        ],
        created_at=session.created_at,
        updated_at=session.updated_at,
    )


def build_metric_sink(database):
    """Build a callback that stores request events under their response identifiers."""

    service = HubMetricsService(HubMetricsRepository(database))

    def sink(event: Event) -> None:
        """Persist the supplied tracking data through the configured metric service."""
        stored = service.add_metric(
            Metric(
                id=event.id_request,
                latency=event.latency,
                response_status=event.response_status,
                endpoint=event.endpoint,
                origin=event.origin,
            )
        )
        record_hub_metric(stored)

    return sink


def build_aeko_metrics_sink(database):
    """Build a callback that stores SDK run metrics and agent invocations in call order."""

    service = AekoMetricsService(AekoMetricsRepository(database))

    def sink(metrics) -> None:
        """Persist the supplied tracking data through the configured metric service."""
        stored = service.add_metric(metric_from_sdk_run(metrics))
        record_aeko_run(stored)

    return sink


def build_inventory_analyzer() -> AekoInventoryAnalyzer:
    """Create an analyzer with independent context for one report."""
    return _InventoryAnalyzer()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database, cache, SDK tools, and metric sinks, then release connections on shutdown."""
    global mongo_client, redis_client, db

    silence_uvicorn_access_log()
    configure_opentelemetry()

    mongo_client = MongoClient(MONGO_URI)
    db = mongo_client[DB_NAME]
    app.state.db = db

    redis_client = Redis.from_url(REDIS_URI)
    app.state.redis = redis_client

    set_event_sink(build_metric_sink(db))

    set_aeko_metrics_sink(build_aeko_metrics_sink(db))

    Aeko.config(
        GEMINI_API_KEY,
        fast_model=AEKO_FAST_MODEL,
        slow_model=AEKO_SLOW_MODEL,
        max_tokens=_int_or_none(AEKO_MAX_TOKENS),
        report_max_tokens=_int_or_none(AEKO_REPORT_MAX_TOKENS),
        temperature=_float_or_none(AEKO_TEMPERATURE),
        top_p=_float_or_none(AEKO_TOP_P),
        top_k=_int_or_none(AEKO_TOP_K),
    )
    AekoMessenger.set_tools(AEKO_TOOLS)

    app.state._state["aeko_messenger_factory"] = build_messenger
    app.state._state["aeko_session_factory"] = build_session
    app.state._state["aeko_inventory_analyzer_factory"] = build_inventory_analyzer

    try:
        with operation(Module.DATABASE, "mongo.ping"):
            db.command("ping")
    except Exception as exc:
        raise RuntimeError(f"Failed to connect to MongoDB: {exc}") from exc

    try:
        with operation(Module.DATABASE, "redis.ping"):
            redis_client.ping()
    except Exception as exc:
        raise RuntimeError(f"Failed to connect to Redis: {exc}") from exc

    session_service = SessionService(
        SessionRepository(db),
        SessionCacheRepository(redis_client, scan_count=REDIS_SCAN_COUNT),
        inactivity_minutes=SESSION_INACTIVITY_MINUTES,
    )
    configure_mongo_tools(
        improvement_plans=ImprovementPlanService(ImprovementPlanRepository(db)),
        users=UserService(UserRepository(db)),
        sessions=session_service,
    )
    configure_chroma_tools(
        users=UserService(UserRepository(db)),
        improvement_plans=ImprovementPlanService(ImprovementPlanRepository(db)),
    )

    user_service = UserService(UserRepository(db))
    app.state.oauth = OAuthService(OAuthCodeRepository(redis_client), user_service)

    ticket_service = UploadTicketService(UploadTicketRepository(redis_client))
    configure_inventory_tools(
        tickets=ticket_service,
        create_inventory=create_inventory,
        plans=ImprovementPlanService(ImprovementPlanRepository(db)),
    )
    configure_ask_aeko(
        a2a=A2AService(UserService(UserRepository(db)), session_service, UserRepository(db)),
        aeko_messenger_factory=build_messenger,
        aeko_session_factory=build_session,
    )
    app.state.ticket_service = ticket_service

    if MCP_WARM_UP.strip().lower() not in {"false", "0", "no"}:
        _warm_up_mcp_sessions()

    async with chatgpt_mcp.session_manager.run():
        yield

    configure_mongo_tools()
    configure_chroma_tools()
    configure_inventory_tools()
    configure_ask_aeko()
    set_event_sink(None)
    set_aeko_metrics_sink(None)
    shutdown_opentelemetry()

    for session in MCP_SESSIONS:
        session.close()

    redis_client.close()
    mongo_client.close()

OPENAPI_TAGS = [
    {
        "name": "Users",
        "description": "Endpoints for retrieving user profile data used by the AI gateway.",
    },
    {
        "name": "Sessions",
        "description": "Endpoints for listing sessions and session messages.",
    },
    {
        "name": "Reports",
        "description": "Endpoints for analyzing inventories and reading the stored textual improvement plan.",
    },
]

app = FastAPI(
    lifespan=lifespan,
    title="Aether AI Gateway",
    version="1.0.0",
    description=(
        "HTTP API for user, session, and report workflows in the Aether core gateway. "
        "Every response carries an X-Request-Id header: the identifier of that request "
        "in the hub_metrics base."
    ),
    openapi_tags=OPENAPI_TAGS,
)


app.add_middleware(RequestLogMiddleware)

app.include_router(user_router)
app.include_router(session_router)
app.include_router(upload_ticket_router)
app.include_router(improvement_plan_router)
app.include_router(oauth_router)

app.mount(CHATGPT_MCP_PREFIX, chatgpt_mcp_app)
