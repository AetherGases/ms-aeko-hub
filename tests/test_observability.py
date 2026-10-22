"""Verify observability behavior and error handling."""

import asyncio
import re

import pytest
from fastapi import FastAPI

from cmd.api.integrations import climatiq_api
from cmd.api.integrations.mcp import mcp_session
from cmd.api.integrations.mcp.mcp_session import PersistentMCPSession
from cmd.api.tools import calculator, finance
from improvement_plan.database.repository import Repository as ImprovementPlanRepository
from session.database.repository import Repository as SessionRepository

from tests.mongo_doubles import StubCollection, StubDatabase
from user.database.repository import Repository as UserRepository

LINE = re.compile(r"^\[aeko-hub\] \[(?P<module>\w+)\] \[[^\]]+\] (?P<description>.*)$")

USER_DOCUMENT = {
    "_id": "65a8b3d6c0f8e1d7f4b2c010",
    "id_external_user": 12345,
    "role": "analyst",
    "usecase": "report_generation",
}

SESSION_DOCUMENT = {
    "_id": "65a8b3d6c0f8e1d7f4b2c001",
    "id_user": "65a8b3d6c0f8e1d7f4b2c010",
    "name": "Escopo 1",
    "messages": [],
}


@pytest.fixture(autouse=True)
def no_color_override(monkeypatch):
    """Clear the color override for terminal-detection tests."""
    monkeypatch.delenv("AEKO_LOG_COLOR", raising=False)


def entries(capsys):
    """Parse captured log output into module and description pairs."""
    parsed = []
    for line in capsys.readouterr().out.splitlines():
        match = LINE.match(line)
        if match:
            parsed.append((match["module"], match["description"]))
    return parsed


def descriptions(capsys, module):
    """Return captured operation descriptions for the selected module."""
    return [description for name, description in entries(capsys) if name == module]


def test_a_user_read_is_logged(capsys):
    """Verify that a user read is logged."""
    repository = UserRepository(
        StubDatabase(user=StubCollection(find_one_result=USER_DOCUMENT))
    )

    repository.get_user(12345)

    assert descriptions(capsys, "database")[0].startswith("user.get_user succeeded in ")


def test_a_user_read_that_finds_nobody_is_logged_as_a_failure(capsys):
    """Verify that a user read that finds nobody is logged as a failure."""
    repository = UserRepository(StubDatabase(user=StubCollection(find_one_result=None)))

    with pytest.raises(ValueError):
        repository.get_user(12345)

    assert descriptions(capsys, "database")[0].startswith("user.get_user failed after ")


def test_a_database_error_reaches_the_log_by_name(capsys):
    """Verify that a database error reaches the log by name."""
    collection = StubCollection(error=ConnectionError("connection refused"))
    repository = UserRepository(StubDatabase(user=collection))

    with pytest.raises(RuntimeError):
        repository.get_user(12345)

    assert descriptions(capsys, "database")[0].endswith(
        ": RuntimeError: Error fetching user from database: connection refused"
    )


def test_a_session_read_is_logged_under_its_own_name(capsys):
    """Verify that a session read is logged under its own name."""
    database = StubDatabase(session=StubCollection(find_one_result=SESSION_DOCUMENT))

    SessionRepository(database).get_session("65a8b3d6c0f8e1d7f4b2c001")

    assert descriptions(capsys, "database")[0].startswith(
        "session.get_session succeeded in "
    )


def test_a_session_write_is_logged(capsys):
    """Verify that a session write is logged."""
    database = StubDatabase(session=StubCollection())

    SessionRepository(database).update_name("65a8b3d6c0f8e1d7f4b2c001", "Escopo 2")

    assert descriptions(capsys, "database")[0].startswith(
        "session.update_name succeeded in "
    )


def test_an_improvement_plan_read_is_logged(capsys):
    """Verify that an improvement plan read is logged."""
    collection = StubCollection(
        find_one_result={"_id": "1", "id_external_inventory": 7}
    )
    database = StubDatabase(improvement_plan=collection)

    ImprovementPlanRepository(database).get_by_id_external_inventory(7)

    assert descriptions(capsys, "database")[0].startswith(
        "improvement_plan.get_by_id_external_inventory succeeded in "
    )


def test_the_startup_ping_is_logged_as_a_database_access(capsys, api_main):
    """Verify that the startup ping is logged as a database access."""

    async def start_and_stop():
        """Start the test session and close it after use."""
        async with api_main.lifespan(FastAPI()):
            pass

    asyncio.run(start_and_stop())

    assert any(
        line.startswith("mongo.ping succeeded in ")
        for line in descriptions(capsys, "database")
    )


class FakeTool:
    def __init__(self, name, result=None, fails_with=None):
        self.name = name
        self.result = result
        self.fails_with = fails_with

    async def ainvoke(self, kwargs):
        """Record an asynchronous tool invocation and return its scripted response."""
        if self.fails_with is not None:
            raise self.fails_with
        return self.result


class FakeSessionContext:
    def __init__(self, client):
        self._client = client

    async def __aenter__(self):
        self._client.opened += 1
        return self._client

    async def __aexit__(self, *exc_info):
        return False


class FakeClient:
    def __init__(self, tools):
        self.tools = tools
        self.opened = 0

    def session(self, server_name):
        """Provide a simulated MCP session context."""
        return FakeSessionContext(self)


@pytest.fixture(autouse=True)
def fake_tool_loading(monkeypatch):
    """Replace MCP tool discovery with scripted tools."""

    async def load_tools(session, **kwargs):
        """Return scripted tools for MCP session discovery."""
        return session.tools

    monkeypatch.setattr(mcp_session, "load_mcp_tools", load_tools)


@pytest.fixture
def closing():
    """Close the test session after use."""
    sessions = []
    yield sessions.append
    for session in sessions:
        session.close()


def build_session(tools):
    """Build a session fixture with configurable dependencies."""
    client = FakeClient(tools)
    return PersistentMCPSession("chroma", lambda: client)


def test_opening_a_server_is_logged(capsys, closing):
    """Verify that opening a server is logged."""
    session = build_session([FakeTool("query_gases_info", result="ok")])
    closing(session)

    session.start()

    assert descriptions(capsys, "mcp")[0].startswith("chroma.start succeeded in ")


def test_a_warm_server_is_not_logged_again(capsys, closing):
    """Verify that a warm server is not logged again."""
    session = build_session([FakeTool("query_gases_info", result="ok")])
    closing(session)

    session.start()
    capsys.readouterr()
    session.start()

    assert descriptions(capsys, "mcp") == []


def test_a_server_that_never_comes_up_is_logged_red(capsys, closing):
    """Verify that a server that never comes up is logged red."""
    session = PersistentMCPSession(
        "chroma",
        lambda: (_ for _ in ()).throw(RuntimeError("npx is not installed")),
    )
    closing(session)

    with pytest.raises(Exception):
        session.start()

    assert descriptions(capsys, "mcp")[0].startswith("chroma.start failed after ")


def test_a_tool_call_over_the_session_is_logged(capsys, closing):
    """Verify that a tool call over the session is logged."""
    session = build_session([FakeTool("query_gases_info", result="ok")])
    closing(session)

    session.call_tool("query_gases_info", query="metano")

    assert "chroma.query_gases_info succeeded in " in " ".join(
        descriptions(capsys, "mcp")
    )


def test_a_tool_the_server_does_not_expose_is_logged_red(capsys, closing):
    """Verify that a tool the server does not expose is logged red."""
    session = build_session([FakeTool("query_gases_info", result="ok")])
    closing(session)

    with pytest.raises(LookupError):
        session.call_tool("drop_everything")

    failed = [line for line in descriptions(capsys, "mcp") if "failed after" in line]
    assert failed[0].startswith("chroma.drop_everything failed after ")


def test_closing_the_server_is_logged(capsys, closing):
    """Verify that closing the server is logged."""
    session = build_session([FakeTool("query_gases_info", result="ok")])
    closing(session)
    session.start()
    capsys.readouterr()

    session.close()

    assert descriptions(capsys, "mcp") == ["chroma.close ended the session"]


def test_closing_a_session_that_was_never_opened_says_nothing(capsys):
    """Verify that closing a session that was never opened says nothing."""
    build_session([]).close()

    assert entries(capsys) == []


def test_the_calculator_is_logged_by_the_name_the_agent_calls_it(capsys):
    """Verify that the calculator is logged by the name the agent calls it."""
    calculator._calculate("1200 * 2.68")

    assert descriptions(capsys, "tool")[0].startswith("calculator succeeded in ")


def test_an_expression_the_calculator_refuses_is_logged_red(capsys):
    """Verify that an expression the calculator refuses is logged red."""
    with pytest.raises(ValueError):
        calculator._calculate("__import__('os').system('ls')")

    assert descriptions(capsys, "tool")[0].startswith("calculator failed after ")


def test_the_roi_tool_is_logged(capsys):
    """Verify that the roi tool is logged."""
    finance._calculate_roi(
        {"capex": 1000, "wacc_monthly": 0.01, "monthly_cash_flow": 100}
    )

    assert descriptions(capsys, "tool")[0].startswith("calculate_roi succeeded in ")


def test_the_payback_tool_is_logged(capsys):
    """Verify that the payback tool is logged."""
    finance._calculate_payback(
        {"capex": 1000, "wacc_monthly": 0.01, "monthly_cash_flow": 100}
    )

    assert descriptions(capsys, "tool")[0].startswith("calculate_payback succeeded in ")


def test_a_refused_finance_request_is_logged_red(capsys):
    """Verify that a refused finance request is logged red."""
    with pytest.raises(ValueError):
        finance._calculate_roi(
            {"capex": 0, "wacc_monthly": 0.01, "monthly_cash_flow": 100}
        )

    assert descriptions(capsys, "tool")[0].startswith("calculate_roi failed after ")


def test_an_mcp_backed_tool_leaves_both_a_tool_and_an_mcp_line(
    capsys, monkeypatch, closing
):
    """Verify that an mcp backed tool leaves both a tool and an mcp line."""
    from cmd.api.integrations.mcp import chroma_mcp

    session = build_session([FakeTool("query_gases_info", result="ok")])
    closing(session)
    monkeypatch.setattr(chroma_mcp, "CHROMA_SESSION", session)

    chroma_mcp._query_gases_info("metano")

    written = entries(capsys)
    tool_lines = [line for module, line in written if module == "tool"]
    mcp_lines = [line for module, line in written if module == "mcp"]

    assert len(tool_lines) == 1
    assert tool_lines[0].startswith("query_gases_info succeeded in ")
    assert any(
        line.startswith("chroma.query_gases_info succeeded in ") for line in mcp_lines
    )


def test_a_climatiq_search_is_logged_as_an_integration(capsys, monkeypatch):
    """Verify that a climatiq search is logged as an integration."""
    monkeypatch.setattr(
        climatiq_api, "_request", lambda *args, **kwargs: {"results": []}
    )

    climatiq_api._climatiq_search("diesel")

    assert descriptions(capsys, "integration")[0].startswith(
        "climatiq_search succeeded in "
    )


def test_a_climatiq_failure_is_logged_red_with_the_vendors_message(capsys, monkeypatch):
    """Verify that a climatiq failure is logged red with the vendors message."""

    def fail(*args, **kwargs):
        """Raise a test failure from the supplied dependency."""
        raise climatiq_api.ClimatiqError("Climatiq returned 502")

    monkeypatch.setattr(climatiq_api, "_request", fail)

    with pytest.raises(climatiq_api.ClimatiqError):
        climatiq_api._climatiq_search("diesel")

    assert descriptions(capsys, "integration")[0].endswith(
        ": ClimatiqError: Climatiq returned 502"
    )


def test_a_climatiq_estimate_is_logged(capsys, monkeypatch):
    """Verify that a climatiq estimate is logged."""
    monkeypatch.setattr(climatiq_api, "_request", lambda *args, **kwargs: {"co2e": 1})

    climatiq_api._climatiq_estimate(
        {
            "activity_id": "electricity-supply_grid-source_residual_mix",
            "parameters": {"energy": 1, "energy_unit": "kWh"},
        }
    )

    assert descriptions(capsys, "integration")[0].startswith(
        "climatiq_estimate succeeded in "
    )
