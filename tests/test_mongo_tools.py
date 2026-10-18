"""Verify typed Mongo tools read through domain services."""

import importlib

import pytest
from langchain_core.tools import Tool

from cmd.api.tools import constants as tool_constants
from cmd.api.tools import mongo_tools
from improvement_plan.entity import ImprovementPlan
from session.entity import Message, Session
from user.entity import User, UserMemory


IMPROVEMENT_PLAN_TOOL_NAMES = {
    "get_improvement_plan_by_inventory",
    "get_improvement_plan_problem",
    "get_improvement_plan_method",
    "get_improvement_plan_reasoning",
    "list_latest_improvement_plans",
}

USER_MEMORY_TOOL_NAMES = {
    "get_user_profile_by_external_id",
    "list_user_memory_fields",
    "get_user_memory_by_field",
    "list_user_memories",
}

PLAN_TOOL_DESCRIPTIONS = {
    "get_improvement_plan_by_inventory": "GET_IMPROVEMENT_PLAN_BY_INVENTORY_DESCRIPTION",
    "get_improvement_plan_problem": "GET_IMPROVEMENT_PLAN_PROBLEM_DESCRIPTION",
    "get_improvement_plan_method": "GET_IMPROVEMENT_PLAN_METHOD_DESCRIPTION",
    "get_improvement_plan_reasoning": "GET_IMPROVEMENT_PLAN_REASONING_DESCRIPTION",
    "list_latest_improvement_plans": "LIST_LATEST_IMPROVEMENT_PLANS_DESCRIPTION",
}

USER_MEMORY_TOOL_DESCRIPTIONS = {
    "get_user_profile_by_external_id": "GET_USER_PROFILE_BY_EXTERNAL_ID_DESCRIPTION",
    "list_user_memory_fields": "LIST_USER_MEMORY_FIELDS_DESCRIPTION",
    "get_user_memory_by_field": "GET_USER_MEMORY_BY_FIELD_DESCRIPTION",
    "list_user_memories": "LIST_USER_MEMORIES_DESCRIPTION",
}

PROFILE_WRITE_TOOL_NAMES = {"update_user_profile"}

PROFILE_WRITE_TOOL_DESCRIPTIONS = {
    "update_user_profile": "UPDATE_USER_PROFILE_DESCRIPTION",
}

SESSION_TOOL_DESCRIPTIONS = {
    "list_user_session_names": "LIST_USER_SESSION_NAMES_DESCRIPTION",
    "get_session_messages_by_name": "GET_SESSION_MESSAGES_BY_NAME_DESCRIPTION",
    "get_latest_session_messages": "GET_LATEST_SESSION_MESSAGES_DESCRIPTION",
    "count_user_sessions": "COUNT_USER_SESSIONS_DESCRIPTION",
}

SESSION_TOOL_NAMES = {
    "list_user_session_names",
    "get_session_messages_by_name",
    "get_latest_session_messages",
    "count_user_sessions",
}

USER_ID = "65a8b3d6c0f8e1d7f4b2c010"
MS_AUTH_PROFILE = {
    "id": 12345,
    "cpf": "12345678901",
    "email": "caio@example.com",
    "name": "Caio Marcos",
    "phone": "11999999999",
    "image": {"id": 10, "name": "profile.jpg", "path": "/images/profiles/profile.jpg"},
    "permissions": [],
    "enterprise": {
        "id": 90,
        "name": "Aether Industria SA",
        "tradeName": "Aether",
        "cnpj": "12345678000199",
    },
    "unit": {"id": 1, "cnae": "6201500", "cnpj": "12345678000199", "isActive": True},
}
USER = User(
    id=USER_ID,
    id_external_user=12345,
    role="analyst",
    usecase="report_generation",
)
COMPANY_USER = User(
    id=USER_ID,
    id_external_user=12345,
    role="analyst",
    usecase="report_generation",
    id_external_company=90,
)
PLAN = ImprovementPlan(
    id="plan-1",
    id_external_inventory=42,
    defined_problem="flaring",
    method="PDCA",
    reasoning="replace the flare",
    updated_at="2026-07-26T14:30:00Z",
)
MEMORY = UserMemory(
    id="m1",
    id_user=USER_ID,
    field="preferred_language",
    description="pt-BR",
)
SESSION = Session(
    id="s1",
    id_user=USER_ID,
    name="Weekly emissions review",
    messages=[],
)
MESSAGE = Message(
    input="Summarize this session.",
    output="Here is the summary.",
    submitted_at="2026-07-26T14:30:00Z",
)


class StubPlanService:
    """Stands in for the improvement-plan service the tools read from."""

    def __init__(self, *, plan=None, plans=None, error=None):
        self.plan = plan
        self.plans = [] if plans is None else list(plans)
        self.error = error
        self.calls = []

    def get_by_id_external_inventory(self, identifier):
        """Record a lookup by inventory and return the scripted plan."""
        self.calls.append(("get_by_id_external_inventory", identifier))
        if self.error is not None:
            raise self.error
        if self.plan is None:
            raise ValueError(f"Improvement plan with id_external_inventory {identifier} not found.")
        return self.plan

    def list_latest(self, n, id_external_company):
        """Record a latest-plan listing and return the scripted plans."""
        self.calls.append(("list_latest", n, id_external_company))
        if self.error is not None:
            raise self.error
        return list(self.plans)


class StubUserService:
    """Stands in for the user service the tools read from."""

    def __init__(self, *, user=None, memories=None, error=None):
        self.user = user
        self.memories = [] if memories is None else list(memories)
        self.error = error
        self.calls = []

    def get_mongo_user(self, identifier):
        """Record a user lookup and return the scripted user."""
        self.calls.append(("get_mongo_user", identifier))
        if self.error is not None:
            raise self.error
        if self.user is None:
            raise ValueError(f"User with id_external_user {identifier} not found.")
        return self.user

    def get_user_memories(self, id_user):
        """Record a memory listing and return the scripted memories."""
        self.calls.append(("get_user_memories", id_user))
        if self.error is not None:
            raise self.error
        return list(self.memories)

    def update_user_profile(self, id_external_user, *, role=None, usecase=None):
        """Record a profile update and return the user with applied fields."""
        self.calls.append(("update_user_profile", id_external_user, role, usecase))
        if self.error is not None:
            raise self.error
        if role is None and usecase is None:
            raise ValueError("At least one of role or usecase must be supplied.")
        if self.user is None:
            raise ValueError(f"User with id_external_user {id_external_user} not found.")
        if role is not None:
            self.user.role = role
        if usecase is not None:
            self.user.usecase = usecase
        return self.user

class StubSessionService:
    """Stands in for the session service the tools read from."""

    def __init__(self, *, sessions=None, messages=None, empty=False):
        self.sessions = [] if sessions is None else list(sessions)
        self.messages = [] if messages is None else list(messages)
        self.empty = empty
        self.calls = []

    def get_user_sessions(self, id_user):
        """Record a session listing and raise when the store is empty."""
        self.calls.append(("get_user_sessions", id_user))
        if self.empty or not self.sessions:
            raise ValueError(f"No sessions found for user with id_user {id_user}.")
        return list(self.sessions)

    def get_session_messages(self, id_session):
        """Record a message listing and return the scripted messages."""
        self.calls.append(("get_session_messages", id_session))
        return list(self.messages)


@pytest.fixture(autouse=True)
def reset_mongo_tools():
    """Clear bound domain services around each test."""
    mongo_tools.configure()
    yield
    mongo_tools.configure()


def bind(*, plans=None, users=None, sessions=None):
    """Bind stub services to the Mongo tools."""
    mongo_tools.configure(improvement_plans=plans, users=users, sessions=sessions)


def test_mongo_mcp_module_is_gone():
    """Verify that mongo mcp module is gone."""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("cmd.api.integrations.mcp.mongo_mcp")


def test_mongo_tools_do_not_expose_raw_mongo_filters():
    """Verify that mongo tools do not expose raw mongo filters."""
    assert not hasattr(mongo_tools, "_parse_filter")
    assert not hasattr(mongo_tools, "_find_improvement_plan")
    assert not hasattr(mongo_tools, "_find_user_memory")
    assert not hasattr(mongo_tools, "_call_mongo_tool")


def test_get_improvement_plan_by_inventory_reads_through_the_plan_service():
    """Verify that get improvement plan by inventory reads through the plan service."""
    plans = StubPlanService(plan=PLAN)
    bind(plans=plans)

    result = mongo_tools._get_improvement_plan_by_inventory(42)

    assert result == [
        {
            "id_external_inventory": 42,
            "defined_problem": "flaring",
            "method": "PDCA",
            "reasoning": "replace the flare",
            "updated_at": "2026-07-26T14:30:00Z",
        }
    ]
    assert plans.calls == [("get_by_id_external_inventory", 42)]
    assert "_id" not in result[0]


def test_get_improvement_plan_by_inventory_accepts_a_numeric_string():
    """Verify that get improvement plan by inventory accepts a numeric string."""
    plans = StubPlanService(plan=PLAN)
    bind(plans=plans)

    mongo_tools._get_improvement_plan_by_inventory("42")

    assert plans.calls == [("get_by_id_external_inventory", 42)]


@pytest.mark.parametrize("bad", [None, "", "   ", "abc", 0, -1, True, False, 4.2])
def test_get_improvement_plan_by_inventory_rejects_an_unusable_identifier(bad):
    """Verify that get improvement plan by inventory rejects an unusable identifier."""
    plans = StubPlanService(plan=PLAN)
    bind(plans=plans)

    with pytest.raises(ValueError):
        mongo_tools._get_improvement_plan_by_inventory(bad)

    assert plans.calls == []


def test_get_improvement_plan_by_inventory_raises_when_missing():
    """Verify that get improvement plan by inventory raises when missing."""
    bind(plans=StubPlanService())

    with pytest.raises(ValueError, match="id_external_inventory"):
        mongo_tools._get_improvement_plan_by_inventory(42)


def test_get_improvement_plan_problem_returns_only_the_problem():
    """Verify that get improvement plan problem returns only the problem."""
    bind(plans=StubPlanService(plan=PLAN))

    assert mongo_tools._get_improvement_plan_problem(42) == [
        {"id_external_inventory": 42, "defined_problem": "flaring"}
    ]


def test_get_improvement_plan_method_returns_only_the_method():
    """Verify that get improvement plan method returns only the method."""
    bind(plans=StubPlanService(plan=PLAN))

    assert mongo_tools._get_improvement_plan_method(42) == [
        {"id_external_inventory": 42, "method": "PDCA"}
    ]


def test_get_improvement_plan_reasoning_returns_only_the_reasoning():
    """Verify that get improvement plan reasoning returns only the reasoning."""
    bind(plans=StubPlanService(plan=PLAN))

    assert mongo_tools._get_improvement_plan_reasoning(42) == [
        {"id_external_inventory": 42, "reasoning": "replace the flare"}
    ]


def test_mongo_tools_do_not_expose_regex_plan_search():
    """Verify that mongo tools do not expose regex plan search."""
    assert not hasattr(mongo_tools, "_search_improvement_plans_by_problem")
    assert not hasattr(mongo_tools, "_search_improvement_plans_by_method")


def test_list_latest_improvement_plans_asks_the_service_for_n_and_sorts_newest_first():
    """Verify that list latest improvement plans asks the service for n and sorts newest first."""
    older = ImprovementPlan(
        id="plan-old",
        id_external_inventory=41,
        defined_problem="flaring",
        updated_at="2026-01-01T00:00:00Z",
    )
    newer = ImprovementPlan(
        id="plan-new",
        id_external_inventory=43,
        defined_problem="flaring",
        updated_at="2026-09-01T00:00:00Z",
    )
    plans = StubPlanService(plans=[older, newer])
    bind(plans=plans, users=StubUserService(user=COMPANY_USER))

    result = mongo_tools._list_latest_improvement_plans(12345, 2)

    assert [item["id_external_inventory"] for item in result] == [43, 41]
    assert all("_id" not in item for item in result)
    assert plans.calls == [("list_latest", 2, 90)]


def test_list_latest_improvement_plans_asks_the_service_for_n_and_the_user_company():
    """Verify that list latest asks the service for n and the user company."""
    own = ImprovementPlan(
        id="plan-new",
        id_external_inventory=43,
        id_external_company=90,
        defined_problem="flaring",
        updated_at="2026-09-01T00:00:00Z",
    )
    plans = StubPlanService(plans=[own])
    bind(plans=plans, users=StubUserService(user=COMPANY_USER))

    result = mongo_tools._list_latest_improvement_plans(12345, 2)

    assert [item["id_external_inventory"] for item in result] == [43]
    assert all("_id" not in item and "id_external_company" not in item for item in result)
    assert plans.calls == [("list_latest", 2, 90)]


def test_list_latest_improvement_plans_rejects_a_user_without_company():
    """Verify that list latest rejects a user without company."""
    plans = StubPlanService(plans=[PLAN])
    bind(plans=plans, users=StubUserService(user=USER))

    with pytest.raises(ValueError, match="id_external_company"):
        mongo_tools._list_latest_improvement_plans(12345, 3)

    assert plans.calls == []


def test_list_latest_improvement_plans_accepts_a_numeric_string():
    """Verify that list latest improvement plans accepts a numeric string."""
    plans = StubPlanService(plans=[PLAN])
    bind(plans=plans, users=StubUserService(user=COMPANY_USER))

    mongo_tools._list_latest_improvement_plans(12345, "3")

    assert plans.calls == [("list_latest", 3, 90)]


def test_list_latest_improvement_plans_does_not_cap_at_twenty():
    """Verify that list latest improvement plans does not cap at twenty."""
    plans = [
        ImprovementPlan(id=f"plan-{index}", id_external_inventory=index, updated_at=f"2026-01-{index + 1:02d}T00:00:00Z")
        for index in range(25)
    ]
    bind(plans=StubPlanService(plans=plans), users=StubUserService(user=COMPANY_USER))

    result = mongo_tools._list_latest_improvement_plans(12345, 25)

    assert len(result) == 25


def test_list_latest_improvement_plans_returns_an_empty_list_when_nothing_matches():
    """Verify that list latest improvement plans returns an empty list when nothing matches."""
    bind(plans=StubPlanService(plans=[]), users=StubUserService(user=COMPANY_USER))

    assert mongo_tools._list_latest_improvement_plans(12345, 3) == []


@pytest.mark.parametrize("bad", [None, "", "   ", "abc", 0, -1, True, False, 4.2])
def test_list_latest_improvement_plans_rejects_an_unusable_limit(bad):
    """Verify that list latest improvement plans rejects an unusable limit."""
    plans = StubPlanService(plans=[PLAN])
    bind(plans=plans, users=StubUserService(user=COMPANY_USER))

    with pytest.raises(ValueError):
        mongo_tools._list_latest_improvement_plans(12345, bad)

    assert plans.calls == []


def test_get_user_profile_by_external_id_reads_ms_auth_and_merges_role():
    """Verify that get user profile by external id merges the bound ms-auth profile."""

    from cmd.api.acl.open_ai.identity import (
        bind_id_external_user,
        bind_ms_auth_profile,
        reset_id_external_user,
        reset_ms_auth_profile,
    )

    users = StubUserService(user=USER)
    bind(users=users)
    profile_token = bind_ms_auth_profile(MS_AUTH_PROFILE)
    user_token = bind_id_external_user(12345)
    try:
        result = mongo_tools._get_user_profile_by_external_id(12345)
    finally:
        reset_ms_auth_profile(profile_token)
        reset_id_external_user(user_token)

    assert result["id"] == 12345
    assert result["role"] == "analyst"
    assert result["usecase"] == "report_generation"
    assert result["enterprise"] == MS_AUTH_PROFILE["enterprise"]
    assert users.calls == [("get_mongo_user", 12345)]


def test_list_user_memories_resolves_the_user_then_lists_memories():
    """Verify that list user memories resolves the user then lists memories."""
    second = UserMemory(id="m2", id_user=USER_ID, field="improvement_plan", description="replace the boiler")
    users = StubUserService(user=USER, memories=[MEMORY, second])
    bind(users=users)

    result = mongo_tools._list_user_memories(12345)

    assert result == [
        {"field": "preferred_language", "description": "pt-BR"},
        {"field": "improvement_plan", "description": "replace the boiler"},
    ]
    assert users.calls == [("get_mongo_user", 12345), ("get_user_memories", USER_ID)]


def test_list_user_memories_does_not_query_memories_when_the_user_is_missing():
    """Verify that list user memories does not query memories when the user is missing."""
    users = StubUserService()
    bind(users=users)

    with pytest.raises(ValueError, match="id_external_user"):
        mongo_tools._list_user_memories(12345)

    assert users.calls == [("get_mongo_user", 12345)]


def test_list_user_memory_fields_returns_only_field_names():
    """Verify that list user memory fields returns only field names."""
    bind(users=StubUserService(user=USER, memories=[MEMORY]))

    assert mongo_tools._list_user_memory_fields(12345) == [{"field": "preferred_language"}]


def test_get_user_memory_by_field_returns_the_named_memory():
    """Verify that get user memory by field returns the named memory."""
    users = StubUserService(user=USER, memories=[MEMORY])
    bind(users=users)

    result = mongo_tools._get_user_memory_by_field(12345, "preferred_language")

    assert result == {"field": "preferred_language", "description": "pt-BR"}
    assert users.calls == [("get_mongo_user", 12345), ("get_user_memories", USER_ID)]


@pytest.mark.parametrize("empty", [None, "", "   "])
def test_get_user_memory_by_field_rejects_an_empty_field(empty):
    """Verify that get user memory by field rejects an empty field."""
    users = StubUserService(user=USER, memories=[MEMORY])
    bind(users=users)

    with pytest.raises(ValueError):
        mongo_tools._get_user_memory_by_field(12345, empty)

    assert users.calls == []


def test_get_user_memory_by_field_raises_when_the_field_is_missing():
    """Verify that get user memory by field raises when the field is missing."""
    bind(users=StubUserService(user=USER, memories=[]))

    with pytest.raises(ValueError, match="field"):
        mongo_tools._get_user_memory_by_field(12345, "preferred_language")


def test_list_user_session_names_returns_names_without_messages():
    """Verify that list user session names returns names without messages."""
    bind(users=StubUserService(user=USER), sessions=StubSessionService(sessions=[SESSION]))

    result = mongo_tools._list_user_session_names(12345)

    assert result == [{"name": "Weekly emissions review"}]


def test_list_user_session_names_returns_an_empty_list_when_the_user_has_none():
    """Verify that list user session names returns an empty list when the user has none."""
    bind(users=StubUserService(user=USER), sessions=StubSessionService(empty=True))

    assert mongo_tools._list_user_session_names(12345) == []


def test_get_session_messages_by_name_reads_messages_from_the_named_session():
    """Verify that get session messages by name reads messages from the named session."""
    sessions = StubSessionService(sessions=[SESSION], messages=[MESSAGE])
    bind(users=StubUserService(user=USER), sessions=sessions)

    result = mongo_tools._get_session_messages_by_name(12345, "Weekly emissions review")

    assert result == [
        {
            "input": "Summarize this session.",
            "output": "Here is the summary.",
            "submitted_at": "2026-07-26T14:30:00Z",
        }
    ]
    assert sessions.calls == [
        ("get_user_sessions", USER_ID),
        ("get_session_messages", "s1"),
    ]


def test_get_session_messages_by_name_raises_when_the_session_is_missing():
    """Verify that get session messages by name raises when the session is missing."""
    bind(users=StubUserService(user=USER), sessions=StubSessionService(empty=True))

    with pytest.raises(ValueError, match="session_name"):
        mongo_tools._get_session_messages_by_name(12345, "Weekly emissions review")


def test_get_latest_session_messages_returns_the_newest_n_messages():
    """Verify that get latest session messages returns the newest n messages."""
    messages = [
        Message(input="oldest", output="a", submitted_at="2026-07-24T14:30:00Z"),
        Message(input="middle", output="b", submitted_at="2026-07-25T14:30:00Z"),
        Message(input="newest", output="c", submitted_at="2026-07-26T14:30:00Z"),
    ]
    bind(
        users=StubUserService(user=USER),
        sessions=StubSessionService(sessions=[SESSION], messages=messages),
    )

    result = mongo_tools._get_latest_session_messages(12345, "Weekly emissions review", 2)

    assert result == [
        {"input": "newest", "output": "c", "submitted_at": "2026-07-26T14:30:00Z"},
        {"input": "middle", "output": "b", "submitted_at": "2026-07-25T14:30:00Z"},
    ]


def test_get_latest_session_messages_returns_fewer_when_the_session_is_shorter():
    """Verify that get latest session messages returns fewer when the session is shorter."""
    bind(
        users=StubUserService(user=USER),
        sessions=StubSessionService(
            sessions=[SESSION],
            messages=[Message(input="only", output="one", submitted_at="2026-07-26T14:30:00Z")],
        ),
    )

    result = mongo_tools._get_latest_session_messages(12345, "Weekly emissions review", 5)

    assert len(result) == 1
    assert result[0]["input"] == "only"


def test_get_latest_session_messages_raises_when_the_session_is_missing():
    """Verify that get latest session messages raises when the session is missing."""
    bind(users=StubUserService(user=USER), sessions=StubSessionService(empty=True))

    with pytest.raises(ValueError, match="session_name"):
        mongo_tools._get_latest_session_messages(12345, "Weekly emissions review", 2)


@pytest.mark.parametrize("bad", [None, "", "   ", 0, -1, True, False])
def test_get_latest_session_messages_rejects_an_unusable_limit(bad):
    """Verify that get latest session messages rejects an unusable limit."""
    users = StubUserService(user=USER)
    sessions = StubSessionService(sessions=[SESSION], messages=[MESSAGE])
    bind(users=users, sessions=sessions)

    with pytest.raises(ValueError):
        mongo_tools._get_latest_session_messages(12345, "Weekly emissions review", bad)

    assert users.calls == []
    assert sessions.calls == []


def test_count_user_sessions_returns_the_number_of_sessions():
    """Verify that count user sessions returns the number of sessions."""
    second = Session(id="s2", id_user=USER_ID, name="b", messages=[])
    bind(
        users=StubUserService(user=USER),
        sessions=StubSessionService(sessions=[SESSION, second]),
    )

    assert mongo_tools._count_user_sessions(12345) == {"count": 2}


def test_count_user_sessions_returns_zero_when_the_user_has_none():
    """Verify that count user sessions returns zero when the user has none."""
    bind(users=StubUserService(user=USER), sessions=StubSessionService(empty=True))

    assert mongo_tools._count_user_sessions(12345) == {"count": 0}


def test_tools_raise_when_services_are_not_configured():
    """Verify that tools raise when services are not configured."""
    with pytest.raises(RuntimeError, match="Improvement plan service"):
        mongo_tools._get_improvement_plan_by_inventory(42)


def test_get_improvement_plan_tools_exposes_the_typed_plan_catalog():
    """Verify that get improvement plan tools exposes the typed plan catalog."""
    tools = mongo_tools.get_improvement_plan_tools()

    assert {tool.name for tool in tools} == IMPROVEMENT_PLAN_TOOL_NAMES
    assert all(isinstance(tool, Tool) and tool.description for tool in tools)
    assert all("filter" not in tool.args and "filter_json" not in tool.args for tool in tools)


def test_improvement_plan_tools_load_descriptions_from_the_environment():
    """Verify that improvement plan tools load descriptions from the environment."""
    tools = {tool.name: tool for tool in mongo_tools.get_improvement_plan_tools()}
    for name, constant in PLAN_TOOL_DESCRIPTIONS.items():
        assert tools[name].description == getattr(tool_constants, constant)


def test_get_improvement_plan_by_inventory_tool_declares_the_inventory_argument():
    """Verify that get improvement plan by inventory tool declares the inventory argument."""
    tool = next(
        item
        for item in mongo_tools.get_improvement_plan_tools()
        if item.name == "get_improvement_plan_by_inventory"
    )

    assert set(tool.args) == {"id_external_inventory"}


def test_list_latest_improvement_plans_tool_declares_user_and_n():
    """Verify that list latest improvement plans tool declares user and n."""
    tool = next(
        item
        for item in mongo_tools.get_improvement_plan_tools()
        if item.name == "list_latest_improvement_plans"
    )
    assert set(tool.args) == {"id_external_user", "n"}


def test_get_user_memory_tools_exposes_the_typed_user_catalog():
    """Verify that get user memory tools exposes the typed user catalog."""
    tools = mongo_tools.get_user_memory_tools()

    assert {tool.name for tool in tools} == USER_MEMORY_TOOL_NAMES
    assert all("filter" not in tool.args and "filter_json" not in tool.args for tool in tools)


def test_user_memory_tools_load_descriptions_from_the_environment():
    """Verify that user memory tools load descriptions from the environment."""
    tools = {tool.name: tool for tool in mongo_tools.get_user_memory_tools()}
    for name, constant in USER_MEMORY_TOOL_DESCRIPTIONS.items():
        assert tools[name].description == getattr(tool_constants, constant)


def test_get_user_memory_by_field_tool_declares_external_user_and_field():
    """Verify that get user memory by field tool declares external user and field."""
    tool = next(
        item
        for item in mongo_tools.get_user_memory_tools()
        if item.name == "get_user_memory_by_field"
    )

    assert set(tool.args) == {"id_external_user", "field"}


def test_get_session_tools_exposes_the_typed_session_catalog():
    """Verify that get session tools exposes the typed session catalog."""
    tools = mongo_tools.get_session_tools()

    assert {tool.name for tool in tools} == SESSION_TOOL_NAMES
    assert all("filter" not in tool.args and "filter_json" not in tool.args for tool in tools)


def test_session_tools_load_descriptions_from_the_environment():
    """Verify that session tools load descriptions from the environment."""
    tools = {tool.name: tool for tool in mongo_tools.get_session_tools()}
    for name, constant in SESSION_TOOL_DESCRIPTIONS.items():
        assert tools[name].description == getattr(tool_constants, constant)


def test_get_session_messages_by_name_tool_declares_external_user_and_session_name():
    """Verify that get session messages by name tool declares external user and session name."""
    tool = next(
        item
        for item in mongo_tools.get_session_tools()
        if item.name == "get_session_messages_by_name"
    )

    assert set(tool.args) == {"id_external_user", "session_name"}


def test_get_latest_session_messages_tool_declares_external_user_session_name_and_n():
    """Verify that get latest session messages tool declares external user session name and n."""
    tool = next(
        item
        for item in mongo_tools.get_session_tools()
        if item.name == "get_latest_session_messages"
    )

    assert set(tool.args) == {"id_external_user", "session_name", "n"}


def test_typed_tools_are_backed_by_their_domain_functions():
    """Verify that typed tools are backed by their domain functions."""
    bind(plans=StubPlanService(plan=PLAN))
    tool = next(
        item
        for item in mongo_tools.get_improvement_plan_tools()
        if item.name == "get_improvement_plan_by_inventory"
    )

    assert tool.func(42)[0]["defined_problem"] == "flaring"


def test_update_user_profile_returns_stored_fields():
    """Verify that update user profile persists through the service and returns fields."""
    users = StubUserService(user=USER)
    bind(users=users)

    result = mongo_tools._update_user_profile(12345, role="gestor", usecase="auditoria")

    assert result == {
        "id_external_user": 12345,
        "role": "gestor",
        "usecase": "auditoria",
    }
    assert users.calls == [("update_user_profile", 12345, "gestor", "auditoria")]


def test_update_user_profile_rejects_when_neither_field_is_supplied():
    """Verify that update user profile requires at least one field."""
    bind(users=StubUserService(user=USER))

    with pytest.raises(ValueError, match="At least one"):
        mongo_tools._update_user_profile(12345)


@pytest.mark.parametrize("blank", ["", "   "])
def test_update_user_profile_rejects_blank_role(blank):
    """Verify that update user profile rejects blank role strings."""
    bind(users=StubUserService(user=USER))

    with pytest.raises(ValueError, match="role must be a nonempty string"):
        mongo_tools._update_user_profile(12345, role=blank)


@pytest.mark.parametrize("blank", ["", "   "])
def test_update_user_profile_rejects_blank_usecase(blank):
    """Verify that update user profile rejects blank usecase strings."""
    bind(users=StubUserService(user=USER))

    with pytest.raises(ValueError, match="usecase must be a nonempty string"):
        mongo_tools._update_user_profile(12345, usecase=blank)


def test_update_user_profile_raises_when_user_is_missing():
    """Verify that update user profile does not create a missing user."""
    bind(users=StubUserService(user=None))

    with pytest.raises(ValueError, match="12345 not found"):
        mongo_tools._update_user_profile(12345, role="gestor")


def test_get_user_profile_write_tools_exposes_the_profile_writer():
    """Verify that get user profile write tools exposes only the profile writer."""
    tools = mongo_tools.get_user_profile_write_tools()

    assert {tool.name for tool in tools} == PROFILE_WRITE_TOOL_NAMES
    assert all(isinstance(tool, Tool) and tool.description for tool in tools)
    assert all("filter" not in tool.args and "filter_json" not in tool.args for tool in tools)


def test_profile_write_tools_load_descriptions_from_the_environment():
    """Verify that profile write tools load descriptions from the environment."""
    tools = {tool.name: tool for tool in mongo_tools.get_user_profile_write_tools()}
    for name, constant in PROFILE_WRITE_TOOL_DESCRIPTIONS.items():
        assert tools[name].description == getattr(tool_constants, constant)


def test_update_user_profile_tool_declares_external_user_role_and_usecase():
    """Verify that update user profile tool declares its optional string fields."""
    tool = next(
        item
        for item in mongo_tools.get_user_profile_write_tools()
        if item.name == "update_user_profile"
    )

    assert set(tool.args) == {"id_external_user", "role", "usecase"}
