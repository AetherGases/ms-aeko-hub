"""Verify ChatGPT catalog wrappers hide identity and drop Tavily."""

import pytest

from cmd.api.acl.open_ai.catalog import get_chatgpt_tools


def test_chatgpt_list_latest_schema_has_only_n():
    """Verify that chatgpt list latest schema has only n."""
    from cmd.api.acl.open_ai.catalog import get_chatgpt_tools

    tool = next(
        t for t in get_chatgpt_tools() if t.name == "list_latest_improvement_plans"
    )
    assert set(tool.args) == {"n"}


def test_chatgpt_ask_aeko_schema_has_input_and_optional_session_name():
    """Verify that chatgpt ask aeko schema has input and optional session_name."""
    tool = next(t for t in get_chatgpt_tools() if t.name == "ask_aeko")
    assert set(tool.args) == {"input", "session_name"}
    assert "id_external_user" not in tool.description


def test_chatgpt_query_plan_problems_schema_has_only_query():
    """Verify that chatgpt query plan problems schema has only query."""
    tool = next(
        t for t in get_chatgpt_tools() if t.name == "query_improvement_plan_problems"
    )
    assert set(tool.args) == {"query"}


def test_chatgpt_list_latest_injects_the_bound_user(monkeypatch):
    """Verify that chatgpt list latest injects the bound user."""
    from cmd.api.acl.open_ai import identity
    from cmd.api.acl.open_ai.catalog import get_chatgpt_tools
    from cmd.api.tools import mongo_tools

    received = []

    def fake(id_external_user, n):
        """Record the injected user and limit."""
        received.append((id_external_user, n))
        return []

    monkeypatch.setattr(mongo_tools, "_list_latest_improvement_plans", fake)
    tool = next(
        t for t in get_chatgpt_tools() if t.name == "list_latest_improvement_plans"
    )
    token = identity.bind_id_external_user(12345)
    try:
        tool.func(n=3)
    finally:
        identity.reset_id_external_user(token)
    assert received == [(12345, 3)]


def test_chatgpt_get_plan_hides_another_company(monkeypatch):
    """Verify that chatgpt get plan hides another company."""
    from cmd.api.acl.open_ai import identity
    from cmd.api.acl.open_ai.catalog import get_chatgpt_tools
    from cmd.api.tools import mongo_tools
    from improvement_plan.entity import ImprovementPlan
    from user.entity import User

    other = ImprovementPlan(
        id="p",
        id_external_inventory=502,
        id_external_company=99,
        defined_problem="secret",
        method="x",
        reasoning="y",
        updated_at="2026-01-01T00:00:00Z",
    )

    class Users:
        def get_mongo_user(self, identifier):
            """Return a user belonging to company 90."""
            return User("u1", identifier, "analyst", "report", id_external_company=90)

    class Plans:
        def get_by_id_external_inventory(self, identifier):
            """Return a plan belonging to another company."""
            return other

    mongo_tools.configure(improvement_plans=Plans(), users=Users(), sessions=None)
    tool = next(
        t for t in get_chatgpt_tools() if t.name == "get_improvement_plan_by_inventory"
    )
    token = identity.bind_id_external_user(12345)
    try:
        with pytest.raises(ValueError, match="not found"):
            tool.func(id_external_inventory=502)
    finally:
        identity.reset_id_external_user(token)


def test_chatgpt_list_user_memories_uses_bound_user_not_another_id(monkeypatch):
    """Verify that chatgpt list memories injects the bound user instead of an LLM id."""
    from cmd.api.acl.open_ai import identity
    from cmd.api.acl.open_ai.catalog import get_chatgpt_tools
    from cmd.api.tools import mongo_tools

    received = []

    def fake(id_external_user):
        """Record the injected user."""
        received.append(id_external_user)
        return []

    monkeypatch.setattr(mongo_tools, "_list_user_memories", fake)
    tool = next(t for t in get_chatgpt_tools() if t.name == "list_user_memories")
    token = identity.bind_id_external_user(12345)
    try:
        tool.func()
    finally:
        identity.reset_id_external_user(token)
    assert received == [12345]


def test_chatgpt_get_plan_returns_the_same_catalog_for_the_same_company(monkeypatch):
    """Verify that chatgpt get plan returns the same catalog for the same company."""
    from cmd.api.acl.open_ai import identity
    from cmd.api.acl.open_ai.catalog import get_chatgpt_tools
    from cmd.api.tools import mongo_tools
    from improvement_plan.entity import ImprovementPlan
    from user.entity import User

    own = ImprovementPlan(
        id="p",
        id_external_inventory=502,
        id_external_company=90,
        defined_problem="flaring",
        method="PDCA",
        reasoning="replace the flare",
        updated_at="2026-01-01T00:00:00Z",
    )

    class Users:
        def get_mongo_user(self, identifier):
            """Return a user belonging to company 90."""
            return User("u1", identifier, "analyst", "report", id_external_company=90)

    class Plans:
        def get_by_id_external_inventory(self, identifier):
            """Return a plan belonging to the user's company."""
            return own

    mongo_tools.configure(improvement_plans=Plans(), users=Users(), sessions=None)
    tool = next(
        t for t in get_chatgpt_tools() if t.name == "get_improvement_plan_by_inventory"
    )
    token = identity.bind_id_external_user(12345)
    try:
        result = tool.func(id_external_inventory=502)
    finally:
        identity.reset_id_external_user(token)
    assert result == [
        {
            "id_external_inventory": 502,
            "defined_problem": "flaring",
            "method": "PDCA",
            "reasoning": "replace the flare",
            "updated_at": "2026-01-01T00:00:00Z",
        }
    ]


def test_chatgpt_wrapping_builds_and_runs_with_a_flagged_writer():
    """Verify that a writer flagged for the Consolidador still wraps and executes."""
    from langchain_core.tools import StructuredTool

    from cmd.api.acl.open_ai import identity
    from cmd.api.acl.open_ai.wrappers import wrap_chatgpt_tools

    received = []

    def save(id_external_user: int, role: str):
        """Record the injected user and the role."""
        received.append((id_external_user, role))
        return {"role": role}

    writer = StructuredTool.from_function(
        name="save",
        description="Save a role.",
        func=save,
        metadata={"is_writing": True, "write_failure_message": "{tools}"},
    )

    (wrapped,) = wrap_chatgpt_tools([writer])
    token = identity.bind_id_external_user(12345)
    try:
        result = wrapped.invoke({"role": "gestor"})
    finally:
        identity.reset_id_external_user(token)

    assert result == {"role": "gestor"}
    assert received == [(12345, "gestor")]
    assert set(wrapped.args) == {"role"}
