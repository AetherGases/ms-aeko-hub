"""Verify complete conversation and report flows with isolated external dependencies."""

import re
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from improvement_plan.entity import ImprovementPlan
from improvement_plan.service import Service as ImprovementPlanService
from internal.http import improvement_plan_handlers, session_handlers, user_handlers
from session.entity import Message, Session
from session.service import Service as SessionService
from user.entity import User, UserMemory
from user.service import Service as UserService

REPO_ROOT = Path(__file__).resolve().parents[1]
SUBMITTED_AT = datetime(2026, 7, 26, 14, 30, 0)


ID_INVENTORY = 502
ID_EXTERNAL_USER = 12345
INVENTORY_MARKDOWN = "## Escopo 1\n\n| Fonte | tCO2e |\n| --- | --- |\n| Caldeira | 12400 |"

REPORT_BODY = {
    "id_external_context_inventory": ID_INVENTORY,
    "inventory": INVENTORY_MARKDOWN,
    "id_external_user": ID_EXTERNAL_USER,
    "gases": [{"id": 1, "name": "CO2"}],
    "scopes": [{"id": 1, "name": "Escopo 1"}],
    "categories": [{"id": 1, "name": "Combustão estacionária", "classification": None}],
}

EXTRACTED_INVENTORY_JSON = {
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


TOOLED_AGENTS = {
    "FAQ",
    "Análista de inventários",
    "Analista de Poluentes",
    "Analista de Gases Verdes",
    "Coordenador de Melhoria Contínua",
}


class InMemoryUserRepository:
    def __init__(self, users=None, memories=None):
        self.users = users or {}
        self.memories = list(memories or [])

    def get_user(self, id_external_user):
        """Retrieve a user by external identifier."""
        user = self.users.get(id_external_user)
        if user is None:
            raise ValueError(f"User with id_external_user {id_external_user} not found.")
        return user

    def get_user_by_id(self, id_user):
        """Retrieve a user by internal identifier, returning None when absent."""
        return next((user for user in self.users.values() if user.id == id_user), None)

    def get_user_memories(self, id_user):
        """Retrieve the memories stored for a user."""
        return [memory for memory in self.memories if memory.id_user == id_user]

    def create_user_memory(self, user_memory):
        """Persist a memory associated with a user."""
        self.memories.append(user_memory)


class InMemorySessionRepository:
    def __init__(self, sessions=None, messages=None):
        self.sessions = sessions or {}
        self.messages = messages or {}
        self.created_names = {}

    def get_user_sessions(self, id_user):
        """Retrieve the sessions belonging to a user."""
        sessions = [s for s in self.sessions.values() if s.id_user == id_user]
        if not sessions:
            raise ValueError(f"No sessions found for user with id_user {id_user}.")
        return sessions

    def get_session(self, id_session):
        """Retrieve a session by its internal identifier."""
        session = self.sessions.get(id_session)
        if session is None:
            raise ValueError(f"No session found with id_session {id_session}.")
        return session

    def get_session_messages(self, id_session):
        """Retrieve the stored messages for a session."""
        return self.messages.get(id_session, [])

    def get_session_messages_count(self, id_session):
        """Return the number of messages stored in a session."""
        return len(self.messages.get(id_session, []))

    def create_session(self, id_user, user_repository):
        """Create an empty session for an existing user and return its identifier."""
        id_session = f"session-{len(self.sessions) + 1}"
        self.sessions[id_session] = Session(id=id_session, id_user=id_user, name="", messages=[])
        return id_session

    def save_message(self, id_session, message):
        """Append a message to the session and update its modification timestamp."""
        self.messages.setdefault(id_session, []).append(message)

    def update_name(self, id_session, name):
        """Update the session name and modification timestamp."""
        self.created_names[id_session] = name
        self.sessions[id_session].name = name


class InMemoryImprovementPlanRepository:
    def __init__(self, plans=None):
        self.plans = list(plans or [])

    def get_by_id_external_inventory(self, id_external_inventory):
        """Retrieve the improvement plan associated with an external inventory identifier."""
        plan = next(
            (p for p in self.plans if p.id_external_inventory == id_external_inventory), None
        )
        if plan is None:
            raise ValueError(f"Improvement plan with id_external_inventory {id_external_inventory} not found.")
        return plan

    def create(self, improvement_plan):
        """Persist an improvement plan and return the stored entity."""
        improvement_plan.id = f"plan-{len(self.plans) + 1}"
        improvement_plan.updated_at = improvement_plan.updated_at or datetime.utcnow()
        self.plans.append(improvement_plan)
        return improvement_plan

    def replace(self, improvement_plan):
        """Replace the plan stored for the same external inventory identifier."""
        for index, existing in enumerate(self.plans):
            if existing.id_external_inventory == improvement_plan.id_external_inventory:
                improvement_plan.id = existing.id
                improvement_plan.updated_at = improvement_plan.updated_at or datetime.utcnow()
                self.plans[index] = improvement_plan
                return improvement_plan
        return self.create(improvement_plan)


@pytest.fixture
def seeded_repositories():
    """Create repositories populated with scenario fixtures."""
    user = User(id="u1", id_external_user=12345, role="analyst", usecase="report_generation")
    session = Session(id="s1", id_user="u1", name="Weekly emissions review", messages=[])
    message = Message(
        input="Summarize this session.",
        output="Here is the summary.",
        submitted_at=SUBMITTED_AT,
    )
    memories = [
        UserMemory(
            id="m1",
            id_user="u1",
            field="preferred_language",
            description="Answers in Portuguese",
            expires_at=datetime.utcnow() + timedelta(days=1),
        ),
        UserMemory(
            id="m2",
            id_user="u1",
            field="stale",
            description="Should never reach a prompt",
            expires_at=datetime.utcnow() - timedelta(days=1),
        ),
    ]
    return (
        InMemoryUserRepository(users={12345: user}, memories=memories),
        InMemorySessionRepository(sessions={"s1": session}, messages={"s1": [message]}),
    )


@pytest.fixture
def live_app(api_main, seeded_repositories, monkeypatch):
    """Build the conversation test application with isolated dependencies."""
    user_repository, session_repository = seeded_repositories
    app = api_main.app
    app.dependency_overrides[user_handlers.get_user_service] = lambda: UserService(user_repository)
    app.dependency_overrides[session_handlers.get_session_service] = lambda: SessionService(session_repository)

    monkeypatch.setattr(session_handlers, "UserRepository", lambda db: user_repository)
    with TestClient(app) as client:
        yield client, api_main, user_repository, session_repository
    app.dependency_overrides.clear()


@pytest.fixture
def report_app(live_app, monkeypatch):
    """Build the report test application with isolated dependencies."""
    client, api_main, user_repository, _ = live_app
    plan_repository = InMemoryImprovementPlanRepository()

    client.app.dependency_overrides[improvement_plan_handlers.get_improvement_plan_service] = (
        lambda: ImprovementPlanService(plan_repository)
    )

    monkeypatch.setattr(improvement_plan_handlers, "UserRepository", lambda db: user_repository)

    return client, api_main, plan_repository


def request_report(client, body=None):
    """Submit a report request to the test application."""
    return client.post("/aether-api/v1/ai/report", json=body or REPORT_BODY)


def get_report(client, id_external_inventory=ID_INVENTORY):
    """Read the stored textual plan for an inventory."""
    return client.get(f"/aether-api/v1/ai/report/{id_external_inventory}")


def test_lifespan_configures_the_sdk_from_environment(live_app, fake_sdk):
    """Verify that lifespan configures the sdk from environment."""
    assert fake_sdk.RUNTIME.config_calls == [
        {
            "api_key": "test-gemini-key",
            "fast_model": "fast-model",
            "slow_model": "slow-model",
            "max_tokens": 512,
            "report_max_tokens": 4096,
            "temperature": 0.2,
            "top_p": 0.9,
            "top_k": 40,
        }
    ]
    assert fake_sdk.Aeko.is_configured() is True


def test_lifespan_registers_the_tools_under_the_sdk_agent_names(live_app, fake_sdk):
    """Verify that lifespan registers the tools under the sdk agent names."""
    assert set(fake_sdk.RUNTIME.tools) == TOOLED_AGENTS


def test_registered_tool_keys_are_all_known_agents(live_app, fake_sdk):
    """Verify that registered tool keys are all known agents."""
    assert TOOLED_AGENTS.issubset(set(fake_sdk.AGENT_NAMES))


def test_the_reviewers_are_registered_no_tools(live_app, fake_sdk):
    """Verify that the reviewers are registered no tools."""
    assert not {"Guardrail de Saída", "Verificador de Resposta"} & set(fake_sdk.RUNTIME.tools)


def test_lifespan_registers_every_agent_in_a_single_call(live_app, fake_sdk):
    """Verify that lifespan registers every agent in a single call."""
    assert len(fake_sdk.RUNTIME.set_tools_calls) == 1


CALCULATOR_TOOL_NAME = "calculator"


def test_faq_gets_the_site_map_and_user_memory_tools(live_app, fake_sdk):
    """Verify that faq gets the site map and user memory tools."""
    tool_names = {tool.name for tool in fake_sdk.RUNTIME.tools["FAQ"]}
    assert tool_names == {
        "tavily_map",
        "tavily_search",
        "tavily_research",
        "find_user_memory",
        CALCULATOR_TOOL_NAME,
    }


ROI_TOOL_NAMES = {"calculate_roi", "calculate_payback"}


def test_continuous_improvement_coordinator_also_gets_the_roi_tools(live_app, fake_sdk):
    """Verify that continuous improvement coordinator also gets the roi tools."""
    tool_names = {
        tool.name for tool in fake_sdk.RUNTIME.tools["Coordenador de Melhoria Contínua"]
    }
    assert tool_names == {
        "tavily_search",
        "tavily_research",
        "find_improvement_plan",
        "find_user_memory",
        CALCULATOR_TOOL_NAME,
    } | ROI_TOOL_NAMES


@pytest.mark.parametrize(
    "agent",
    sorted(TOOLED_AGENTS - {"Coordenador de Melhoria Contínua"}),
)
def test_no_other_agent_can_reach_the_roi_tools(live_app, fake_sdk, agent):
    """Verify that no other agent can reach the roi tools."""
    tool_names = {tool.name for tool in fake_sdk.RUNTIME.tools[agent]}
    assert tool_names.isdisjoint(ROI_TOOL_NAMES)


def test_green_gas_analyst_also_gets_the_chroma_vector_search(live_app, fake_sdk):
    """Verify that green gas analyst also gets the chroma vector search."""
    tool_names = {tool.name for tool in fake_sdk.RUNTIME.tools["Analista de Gases Verdes"]}
    assert tool_names == {
        "tavily_search",
        "tavily_research",
        "find_improvement_plan",
        "find_user_memory",
        "query_gases_info",
        CALCULATOR_TOOL_NAME,
    }


@pytest.mark.parametrize(
    "agent",
    sorted(TOOLED_AGENTS - {"Analista de Gases Verdes"}),
)
def test_no_other_agent_can_reach_the_gases_info_collection(live_app, fake_sdk, agent):
    """Verify that no other agent can reach the gases info collection."""
    tool_names = {tool.name for tool in fake_sdk.RUNTIME.tools[agent]}
    assert "query_gases_info" not in tool_names


CLIMATIQ_TOOL_NAMES = {"climatiq_search", "climatiq_estimate"}


def test_pollutant_analyst_also_gets_the_climatiq_calculator(live_app, fake_sdk):
    """Verify that pollutant analyst also gets the climatiq calculator."""
    tool_names = {tool.name for tool in fake_sdk.RUNTIME.tools["Analista de Poluentes"]}
    assert tool_names == {
        "tavily_search",
        "tavily_research",
        "find_improvement_plan",
        "find_user_memory",
        CALCULATOR_TOOL_NAME,
    } | CLIMATIQ_TOOL_NAMES


@pytest.mark.parametrize(
    "agent",
    sorted(TOOLED_AGENTS - {"Analista de Poluentes"}),
)
def test_no_other_agent_can_reach_climatiq(live_app, fake_sdk, agent):
    """Verify that no other agent can reach climatiq."""
    tool_names = {tool.name for tool in fake_sdk.RUNTIME.tools[agent]}
    assert tool_names.isdisjoint(CLIMATIQ_TOOL_NAMES)


def test_inventory_analyst_gets_no_tavily_tools_but_gets_mongo_tools(live_app, fake_sdk):
    """Verify that inventory analyst gets no tavily tools but gets mongo tools."""
    tool_names = {tool.name for tool in fake_sdk.RUNTIME.tools["Análista de inventários"]}
    assert tool_names == {"find_improvement_plan", "find_user_memory", CALCULATOR_TOOL_NAME}


@pytest.mark.parametrize("agent", sorted(TOOLED_AGENTS))
def test_every_agent_gets_the_calculator(live_app, fake_sdk, agent):
    """Verify that every agent gets the calculator."""
    tool_names = {tool.name for tool in fake_sdk.RUNTIME.tools[agent]}

    assert CALCULATOR_TOOL_NAME in tool_names


def test_the_calculator_the_agents_get_actually_calculates(live_app, fake_sdk):
    """Verify that the calculator the agents get actually calculates."""
    tools = fake_sdk.RUNTIME.tools["Analista de Poluentes"]
    calculator = next(tool for tool in tools if tool.name == CALCULATOR_TOOL_NAME)

    assert calculator.tool.func("(1200 * 2.68) / 1000") == "3.216"


def test_the_same_calculator_is_registered_for_every_agent(live_app, fake_sdk):
    """Verify that the same calculator is registered for every agent."""
    calculators = {
        id(tool.tool)
        for agent in TOOLED_AGENTS
        for tool in fake_sdk.RUNTIME.tools[agent]
        if tool.name == CALCULATOR_TOOL_NAME
    }

    assert len(calculators) == 1


def test_lifespan_publishes_sdk_factories_on_app_state(live_app, fake_sdk):
    """Verify that lifespan publishes sdk factories on app state."""
    _, api_main, _, _ = live_app
    state = api_main.app.state._state

    user = User(id="u1", id_external_user=12345, role="analyst", usecase="report_generation")
    messenger = state["aeko_messenger_factory"](user, [])
    session = state["aeko_session_factory"](Session(id="s1", id_user="u1", name="n", messages=[]))

    assert isinstance(messenger, fake_sdk.AekoMessenger)
    assert isinstance(session, fake_sdk.AekoSession)
    assert isinstance(state["aeko_inventory_analyzer_factory"](), fake_sdk.AekoInventoryAnalyzer)


def test_lifespan_publishes_no_shared_sdk_instance(live_app):
    """Verify that lifespan publishes no shared sdk instance."""
    _, api_main, _, _ = live_app
    state = api_main.app.state._state

    assert "aeko_messenger" not in state
    assert "aeko_inventory_analyzer" not in state


def test_every_factory_call_builds_a_fresh_instance(live_app):
    """Verify that every factory call builds a fresh instance."""
    _, api_main, _, _ = live_app
    factory = api_main.app.state._state["aeko_inventory_analyzer_factory"]

    assert factory() is not factory()


def test_lifespan_pings_the_database_and_closes_the_client(api_main):
    """Verify that lifespan pings the database and closes the client."""
    with TestClient(api_main.app):
        pass
    client = api_main.MongoClient.instances[-1]
    redis = api_main.Redis.instances[-1]

    assert client.database.commands == ["ping"]
    assert client.closed is True
    assert redis.closed is True


class FakeMCPSession:
    """One MCP session as the application holds it, without a server behind it."""

    def __init__(self, name, fails_with=None):
        self.name = name
        self.fails_with = fails_with
        self.started = threading.Event()
        self.closed = False

    def start(self):
        """Record the simulated MCP session startup."""
        self.started.set()
        if self.fails_with is not None:
            raise self.fails_with

    def close(self):
        """Record closure of the simulated resource."""
        self.closed = True


def printed_within(capsys, needle, timeout=5.0):
    """Check whether captured output contains the expected text before the deadline."""
    deadline = time.monotonic() + timeout
    output = ""
    while time.monotonic() < deadline:
        output += capsys.readouterr().out
        if needle in output:
            return True
        time.sleep(0.05)
    return False


def test_lifespan_warms_up_every_mcp_session_and_closes_it_afterwards(api_main, monkeypatch):
    """Verify that lifespan warms up every mcp session and closes it afterwards."""
    sessions = (FakeMCPSession("tavily"), FakeMCPSession("mongodb"), FakeMCPSession("chroma"))
    monkeypatch.setattr(api_main, "MCP_SESSIONS", sessions)
    monkeypatch.setattr(api_main, "MCP_WARM_UP", "true")

    with TestClient(api_main.app):
        for session in sessions:
            assert session.started.wait(timeout=5), f"{session.name} was never started"

    assert [session.closed for session in sessions] == [True, True, True]


def test_lifespan_spawns_no_mcp_server_when_warm_up_is_switched_off(api_main, monkeypatch):
    """Verify that lifespan spawns no mcp server when warm up is switched off."""
    session = FakeMCPSession("chroma")
    monkeypatch.setattr(api_main, "MCP_SESSIONS", (session,))
    monkeypatch.setattr(api_main, "MCP_WARM_UP", "false")

    with TestClient(api_main.app):
        pass

    assert session.started.is_set() is False
    assert session.closed is True


def test_lifespan_starts_even_when_an_mcp_server_refuses_to(api_main, monkeypatch, capsys):
    """Verify that lifespan starts even when an mcp server refuses to."""
    session = FakeMCPSession("chroma", fails_with=RuntimeError("CHROMA_API_KEY is not set."))
    monkeypatch.setattr(api_main, "MCP_SESSIONS", (session,))
    monkeypatch.setattr(api_main, "MCP_WARM_UP", "true")

    with TestClient(api_main.app) as client:
        assert client.get("/aether-api/v1/ai/user/12345").status_code in (200, 404, 503)
        assert printed_within(capsys, "CHROMA_API_KEY")


IMPORTS_THE_SDK = re.compile(r"^\s*(?:from|import)\s+aeko\b", re.MULTILINE)


def test_only_the_entry_point_imports_the_sdk():
    """Verify that only the entry point imports the sdk."""
    ignored = {"tests", ".git", ".venv", "venv", "env", "site-packages", "__pycache__"}
    importers = sorted(
        str(path.relative_to(REPO_ROOT)).replace("\\", "/")
        for path in REPO_ROOT.rglob("*.py")
        if ignored.isdisjoint(path.parts)
        and IMPORTS_THE_SDK.search(path.read_text(encoding="utf-8"))
    )

    assert importers == ["cmd/api/main.py", "cmd/memory_generator_worker/main.py"]


def test_journey_user_then_sessions_then_messages(live_app):
    """Verify that journey user then sessions then messages."""
    client, _, _, _ = live_app

    user = client.get("/aether-api/v1/ai/user/12345")
    assert user.status_code == 200
    assert user.json()["role"] == "analyst"

    sessions = client.get("/aether-api/v1/ai/sessions/user/u1")
    assert sessions.status_code == 200
    assert sessions.json() == [{"id": "s1", "name": "Weekly emissions review"}]

    id_session = sessions.json()[0]["id"]
    messages = client.get(f"/aether-api/v1/ai/session/{id_session}/messages")
    assert messages.status_code == 200
    assert messages.json() == [
        {
            "input_message": "Summarize this session.",
            "output_message": "Here is the summary.",
            "submitted_at": SUBMITTED_AT.isoformat(),
        }
    ]


def test_journey_unknown_user_is_404(live_app):
    """Verify that journey unknown user is 404."""
    client, _, _, _ = live_app

    assert client.get("/aether-api/v1/ai/user/99999").status_code == 404
    assert client.get("/aether-api/v1/ai/sessions/user/ghost").status_code == 404


def send(client, **body):
    """Send or capture the request messages used by the test."""
    return client.post("/aether-api/v1/ai/user/session/message", json=body)


def test_send_message_completes_the_round_trip(live_app):
    """Verify that send message completes the round trip."""
    client, _, _, session_repository = live_app

    response = send(client, id_session="s1", input="What is scope 3?", id_user="u1")

    assert response.status_code == 200, response.json()
    assert response.json()["output_message"] == "echo: What is scope 3?"
    assert len(session_repository.get_session_messages("s1")) == 2


def test_send_message_hands_the_session_document_to_the_sdk(live_app, fake_sdk):
    """Verify that send message hands the session document to the sdk."""
    client, _, _, _ = live_app

    send(client, id_session="s1", input="What is scope 3?", id_user="u1")

    message, session, _ = fake_sdk.AekoMessenger.instances[-1].sent[-1]
    assert message == "What is scope 3?"
    assert session.id == "s1"
    assert session.id_user == "u1"

    assert [turn.input for turn in session.messages][0] == "Summarize this session."


def test_send_message_builds_the_messenger_for_the_asking_user(live_app, fake_sdk):
    """Verify that send message builds the messenger for the asking user."""
    client, _, _, _ = live_app

    send(client, id_session="s1", input="hi", id_user="u1")

    messenger = fake_sdk.AekoMessenger.instances[-1]
    assert messenger.user.id_external_user == 12345
    assert messenger.user.role == "analyst"
    assert messenger.user.usecase == "report_generation"


def test_send_message_hands_over_only_the_memories_that_are_still_valid(live_app, fake_sdk):
    """Verify that send message hands over only the memories that are still valid."""
    client, _, _, _ = live_app

    send(client, id_session="s1", input="hi", id_user="u1")

    messenger = fake_sdk.AekoMessenger.instances[-1]
    assert [memory.field for memory in messenger.memories] == ["preferred_language"]


def test_send_message_builds_a_new_messenger_for_every_request(live_app, fake_sdk):
    """Verify that send message builds a new messenger for every request."""
    client, _, _, _ = live_app

    send(client, id_session="s1", input="one", id_user="u1")
    send(client, id_session="s1", input="two", id_user="u1")

    assert len(fake_sdk.AekoMessenger.instances) == 2


def test_send_message_names_a_brand_new_session_after_its_first_message(live_app):
    """Verify that send message names a brand new session after its first message."""
    client, _, _, session_repository = live_app

    response = send(client, id_session="", input="How do I cut boiler emissions?", id_user="u1")

    assert response.status_code == 200
    assert session_repository.created_names == {"session-2": "How do I cut boiler emissions?"}


def test_send_message_returns_502_when_no_reviewer_approved_a_draft(live_app, fake_sdk):
    """Verify that send message returns 502 when no reviewer approved a draft."""
    client, _, _, session_repository = live_app
    fake_sdk.AekoMessenger.next_approved = False

    response = send(client, id_session="s1", input="hi", id_user="u1")

    assert response.status_code == 502
    assert len(session_repository.get_session_messages("s1")) == 1


def test_a_report_answers_with_the_structured_inventory(report_app):
    """Verify that a report answers with the structured inventory."""
    client, _, plan_repository = report_app

    response = request_report(client)

    assert response.status_code == 200
    assert response.json() == EXTRACTED_INVENTORY_JSON
    assert len(plan_repository.plans) == 1
    assert plan_repository.plans[0].id_external_inventory == ID_INVENTORY


def test_the_analyzer_reads_the_markdown_from_the_request(report_app, fake_sdk):
    """Verify that the analyzer reads the markdown from the request."""
    client, *_ = report_app

    request_report(client)

    analyzer = fake_sdk.AekoInventoryAnalyzer.instances[-1]
    inventory, id_external_inventory, id_request, gases, scopes, categories = analyzer.analyzed[0]
    assert inventory == INVENTORY_MARKDOWN
    assert id_external_inventory == ID_INVENTORY
    assert id_request
    assert [(item.id, item.name) for item in gases] == [(1, "CO2")]
    assert [(item.id, item.name) for item in scopes] == [(1, "Escopo 1")]
    assert [(item.id, item.name, item.classification) for item in categories] == [
        (1, "Combustão estacionária", None)
    ]


def test_the_current_plan_of_the_inventory_becomes_the_analyzers_context(report_app, fake_sdk):
    """Verify that the current plan of the inventory becomes the analyzers context."""
    client, _, plan_repository = report_app
    plan_repository.plans.append(
        ImprovementPlan(
            id="p1",
            id_external_inventory=ID_INVENTORY,
            defined_problem="boiler still burning",
            method="swap for heat pumps",
            reasoning="scope 1 dominates",
            updated_at=datetime(2026, 5, 1),
        )
    )

    request_report(client)

    context = fake_sdk.AekoInventoryAnalyzer.instances[-1].context
    assert "boiler still burning" in context
    assert "swap for heat pumps" in context
    assert "scope 1 dominates" in context
    assert len(plan_repository.plans) == 1
    assert plan_repository.plans[0].defined_problem == "high scope 1 emissions"


def test_a_report_records_what_the_analysis_cost(report_app):
    """Verify that a report records what the analysis cost."""
    client, api_main, _ = report_app

    response = request_report(client)

    (document,) = stored_metrics(api_main)
    assert document["flow"] == "analytical"
    assert document["id_request"] == response.headers["x-request-id"]


def test_a_report_without_a_plan_answers_502_and_stores_nothing(report_app, fake_sdk):
    """Verify that a report without a plan answers 502 and stores nothing."""
    client, api_main, plan_repository = report_app
    fake_sdk.AekoInventoryAnalyzer.next_error = fake_sdk.MalformedAgentOutputError(
        "the coordinator never wrote the plan's three headings"
    )

    response = request_report(client)

    assert response.status_code == 502
    assert plan_repository.plans == []

    (document,) = stored_metrics(api_main)
    assert document["flow"] == "analytical"


def test_a_failed_reanalysis_keeps_the_current_plan(report_app, fake_sdk):
    """Verify that a failed reanalysis keeps the current plan."""
    client, _, plan_repository = report_app
    existing = ImprovementPlan(
        id="p1",
        id_external_inventory=ID_INVENTORY,
        defined_problem="old problem",
        method="old method",
        reasoning="old reasoning",
        updated_at=datetime(2026, 5, 1),
    )
    plan_repository.plans.append(existing)
    fake_sdk.AekoInventoryAnalyzer.next_error = fake_sdk.MalformedAgentOutputError("malformed")

    response = request_report(client)

    assert response.status_code == 502
    assert plan_repository.plans == [existing]
    assert get_report(client).json()["defined_problem"] == "old problem"


def test_the_plan_is_remembered_for_the_user_who_asked(report_app, live_app):
    """Verify that the plan is remembered for the user who asked."""
    client, *_ = report_app
    _, _, user_repository, _ = live_app

    request_report(client)

    memory = user_repository.memories[-1]
    assert memory.id_user == "u1"
    assert memory.field == "improvement_plan"


def test_get_report_returns_the_textual_plan(report_app):
    """Verify that get report returns the textual plan."""
    client, *_ = report_app

    request_report(client)
    response = get_report(client)

    assert response.status_code == 200
    assert response.json() == {
        "defined_problem": "high scope 1 emissions",
        "solving_method": "replace the boiler fleet",
        "reasoning": "direct combustion dominates the inventory",
    }


def test_get_report_is_404_when_no_plan_exists(report_app):
    """Verify that get report is 404 when no plan exists."""
    client, *_ = report_app

    response = get_report(client)

    assert response.status_code == 404


def test_get_report_records_hub_metrics_and_no_aeko_metrics(report_app):
    """Verify that get report records hub metrics and no aeko metrics."""
    client, api_main, _ = report_app
    request_report(client)
    api_main.db["aeko_metrics"].documents.clear()
    api_main.db["hub_metrics"].documents.clear()

    response = get_report(client)

    assert response.status_code == 200
    assert stored_metrics(api_main) == []
    (request_row,) = list(api_main.db["hub_metrics"].documents)
    assert request_row["response_status"] == 200
    assert request_row["endpoint"] == "/aether-api/v1/ai/report/{id_external_inventory}"


def test_post_report_records_hub_metrics_for_the_post_template(report_app):
    """Verify that post report records hub metrics for the post template."""
    client, api_main, _ = report_app

    response = request_report(client)

    assert response.status_code == 200
    (request_row,) = list(api_main.db["hub_metrics"].documents)
    assert request_row["response_status"] == 200
    assert request_row["endpoint"] == "/aether-api/v1/ai/report"


def test_an_empty_inventory_is_400_and_does_not_call_aeko(report_app, fake_sdk):
    """Verify that an empty inventory is 400 and does not call aeko."""
    client, *_ = report_app

    response = request_report(client, {**REPORT_BODY, "inventory": "   "})

    assert response.status_code == 400
    assert fake_sdk.AekoInventoryAnalyzer.instances == []


def test_an_unknown_user_is_404_and_stores_nothing(report_app):
    """Verify that an unknown user is 404 and stores nothing."""
    client, _, plan_repository = report_app

    response = request_report(client, {**REPORT_BODY, "id_external_user": 99999})

    assert response.status_code == 404
    assert plan_repository.plans == []


def stored_metrics(api_main):
    """Read metrics persisted by the test request."""
    return list(api_main.db["aeko_metrics"].documents)


def test_send_message_records_what_the_run_cost(live_app):
    """Verify that send message records what the run cost."""
    client, api_main, _, _ = live_app

    send(client, id_session="s1", input="What is scope 3?", id_user="u1")

    (document,) = stored_metrics(api_main)
    assert document["flow"] == "conversational"
    assert document["error_description"] is None
    assert document["latency"] > 0
    assert [agent["name"] for agent in document["used_agents"]] == ["FAQ"]


def test_the_recorded_run_names_the_request_its_caller_was_answered_with(live_app):
    """Verify that the recorded run names the request its caller was answered with."""
    client, api_main, _, _ = live_app

    response = send(client, id_session="s1", input="What is scope 3?", id_user="u1")

    (document,) = stored_metrics(api_main)
    assert document["id_request"] == response.headers["x-request-id"]


def test_the_two_metric_bases_name_the_same_request(live_app):
    """Verify that the two metric bases name the same request."""
    client, api_main, _, _ = live_app

    send(client, id_session="s1", input="What is scope 3?", id_user="u1")

    (request_row,) = list(api_main.db["hub_metrics"].documents)
    (run_row,) = stored_metrics(api_main)
    assert str(request_row["_id"]) == run_row["id_request"]


def test_a_turn_no_reviewer_approved_is_still_recorded(live_app, fake_sdk):
    """Verify that a turn no reviewer approved is still recorded."""
    client, api_main, _, _ = live_app
    fake_sdk.AekoMessenger.next_approved = False

    response = send(client, id_session="s1", input="hi", id_user="u1")

    assert response.status_code == 502
    (document,) = stored_metrics(api_main)
    assert document["error_description"] == fake_sdk.REVIEW_FAILURE


def test_a_request_that_never_reached_the_sdk_records_no_run(live_app):
    """Verify that a request that never reached the sdk records no run."""
    client, api_main, _, _ = live_app

    client.get("/aether-api/v1/ai/sessions/user/u1")

    assert stored_metrics(api_main) == []


def test_the_stored_turn_no_longer_carries_what_it_cost(live_app):
    """Verify that stored messages contain conversation fields without run metrics."""
    client, _, _, session_repository = live_app

    send(client, id_session="s1", input="What is scope 3?", id_user="u1")

    turn = session_repository.get_session_messages("s1")[-1]
    assert set(vars(turn)) == {"input", "output", "submitted_at"}
