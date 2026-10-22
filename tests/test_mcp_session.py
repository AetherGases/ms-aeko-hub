"""Verify mcp session behavior and error handling."""

import asyncio
import threading
import time

import pytest

from cmd.api.integrations.mcp import mcp_session
from cmd.api.integrations.mcp.mcp_session import MCPSessionError, PersistentMCPSession


class FakeTool:
    """One tool as `load_mcp_tools` would hand it over."""

    def __init__(self, name, result=None, fails_with=None, hangs=False):
        self.name = name
        self.result = result
        self.fails_with = fails_with
        self.hangs = hangs
        self.calls = []

    async def ainvoke(self, kwargs):
        """Record an asynchronous tool invocation and return its scripted response."""
        self.calls.append(kwargs)
        if self.hangs:
            await asyncio.sleep(30)
        if self.fails_with is not None:
            raise self.fails_with
        return self.result


class FakeSession:
    def __init__(self, tools):
        self.tools = tools


class FakeClient:
    """`MultiServerMCPClient`, whose `session()` is an async context manager."""

    def __init__(
        self, tools, fails_to_open=None, fails_to_close=None, hangs_on_close=False
    ):
        self.tools = tools
        self.fails_to_open = fails_to_open
        self.fails_to_close = fails_to_close
        self.hangs_on_close = hangs_on_close
        self.server_names = []
        self.opened = 0
        self.closed = 0

    def session(self, server_name):
        """Provide a simulated MCP session context."""
        self.server_names.append(server_name)
        return FakeSessionContext(self)


class FakeSessionContext:
    def __init__(self, client):
        self._client = client

    async def __aenter__(self):
        if self._client.fails_to_open is not None:
            raise self._client.fails_to_open
        self._client.opened += 1
        return FakeSession(self._client.tools)

    async def __aexit__(self, *exc_info):
        self._client.closed += 1
        if self._client.hangs_on_close:
            await asyncio.sleep(30)
        if self._client.fails_to_close is not None:
            raise self._client.fails_to_close
        return False


@pytest.fixture(autouse=True)
def fake_tool_loading(monkeypatch):
    """Replace MCP tool discovery with scripted tools."""

    async def load_tools(session, **kwargs):
        """Return scripted tools for MCP session discovery."""
        return session.tools

    monkeypatch.setattr(mcp_session, "load_mcp_tools", load_tools)


def build_session(*clients, **kwargs):
    """Build a session fixture with configurable dependencies."""

    remaining = list(clients)
    built = []

    def build_client():
        """Build a test client or client double with the supplied dependencies."""
        client = remaining.pop(0) if remaining else built[-1]
        built.append(client)
        return client

    session = PersistentMCPSession("fake-server", build_client, **kwargs)
    session.built = built
    return session


@pytest.fixture
def closing():
    """Close the test session after use."""
    sessions = []
    yield sessions.append
    for session in sessions:
        session.close()


def test_the_session_is_opened_once_and_reused_by_every_call(closing):
    """Verify that the session is opened once and reused by every call."""
    tool = FakeTool("search", result="ok")
    client = FakeClient([tool])
    session = build_session(client)
    closing(session)

    session.call_tool("search", query="a")
    session.call_tool("search", query="b")

    assert client.opened == 1
    assert tool.calls == [{"query": "a"}, {"query": "b"}]


def test_call_tool_returns_what_the_tool_returned(closing):
    """Verify that call tool returns what the tool returned."""
    client = FakeClient([FakeTool("search", result={"documents": [["biogas"]]})])
    session = build_session(client)
    closing(session)

    assert session.call_tool("search", query="metano") == {"documents": [["biogas"]]}


def test_the_session_is_opened_under_the_configured_server_name(closing):
    """Verify that the session is opened under the configured server name."""
    client = FakeClient([FakeTool("search", result="ok")])
    session = build_session(client)
    closing(session)

    session.call_tool("search")

    assert client.server_names == ["fake-server"]


def test_start_opens_the_session_without_calling_anything(closing):
    """Verify that start opens the session without calling anything."""
    client = FakeClient([FakeTool("search", result="ok")])
    session = build_session(client)
    closing(session)

    session.start()

    assert client.opened == 1


def test_the_client_is_built_only_when_the_session_opens(closing):
    """Verify that the client is built only when the session opens."""
    built = []

    def build_client():
        """Build a test client or client double with the supplied dependencies."""
        built.append(1)
        raise RuntimeError("TAVILY_API_KEY is not set.")

    session = PersistentMCPSession("fake-server", build_client)
    closing(session)

    assert built == []
    with pytest.raises(RuntimeError, match="TAVILY_API_KEY"):
        session.call_tool("search")


def test_an_unknown_tool_names_the_ones_the_server_does_expose(closing):
    """Verify that an unknown tool names the ones the server does expose."""
    client = FakeClient([FakeTool("tavily_map"), FakeTool("tavily_search")])
    session = build_session(client)
    closing(session)

    with pytest.raises(LookupError, match="tavily_map, tavily_search"):
        session.call_tool("tavily_crawl")


def test_a_server_that_never_comes_up_says_so(closing):
    """Verify that a server that never comes up says so."""
    client = FakeClient([], fails_to_open=OSError("npx not found"))
    session = build_session(client)
    closing(session)

    with pytest.raises(MCPSessionError, match="npx not found"):
        session.call_tool("search")


def test_a_call_that_never_answers_raises_instead_of_hanging(closing):
    """Verify that a call that never answers raises instead of hanging."""
    client = FakeClient([FakeTool("search", hangs=True)])
    session = build_session(client, call_timeout=0.1)
    closing(session)

    with pytest.raises(MCPSessionError, match="did not answer within"):
        session.call_tool("search")


def test_a_call_that_kept_failing_reports_the_last_error(closing):
    """Verify that a call that kept failing reports the last error."""
    broken = FakeClient([FakeTool("search", fails_with=ConnectionError("pipe closed"))])
    session = build_session(broken, broken)
    closing(session)

    with pytest.raises(MCPSessionError, match="pipe closed"):
        session.call_tool("search")


def test_a_failed_call_is_retried_once_on_a_fresh_session(closing):
    """Verify that a failed call is retried once on a fresh session."""
    dead = FakeClient([FakeTool("search", fails_with=ConnectionError("pipe closed"))])
    healthy = FakeClient([FakeTool("search", result="ok")])
    session = build_session(dead, healthy)
    closing(session)

    assert session.call_tool("search") == "ok"
    assert dead.opened == 1 and healthy.opened == 1


def test_a_dropped_session_is_replaced_on_the_next_call(closing):
    """Verify that a dropped session is replaced on the next call."""
    stuck = FakeClient([FakeTool("search", hangs=True)])
    healthy = FakeClient([FakeTool("search", result="ok")])
    session = build_session(stuck, healthy, call_timeout=0.1)
    closing(session)

    with pytest.raises(MCPSessionError):
        session.call_tool("search")

    assert session.call_tool("search") == "ok"


def test_running_on_a_session_closed_underneath_reports_it(closing):
    """Verify that running on a session closed underneath reports it."""
    session = build_session(FakeClient([FakeTool("search", result="ok")]))
    closing(session)
    session.start()
    session.close()

    coroutine = asyncio.sleep(0)
    try:
        with pytest.raises(ConnectionError, match="closed"):
            session._run(coroutine)
    finally:
        coroutine.close()


def test_closing_leaves_the_session_and_the_server_behind():
    """Verify that closing leaves the session and the server behind."""
    client = FakeClient([FakeTool("search", result="ok")])
    session = build_session(client)
    session.start()

    session.close()

    assert client.closed == 1


def test_closing_survives_a_server_that_fails_on_the_way_out():
    """Verify that closing survives a server that fails on the way out."""
    client = FakeClient(
        [FakeTool("search", result="ok")], fails_to_close=OSError("broken pipe")
    )
    session = build_session(client)
    session.start()

    session.close()

    assert client.closed == 1


def test_closing_gives_up_on_a_server_that_will_not_shut_down():
    """Verify that closing gives up on a server that will not shut down."""
    client = FakeClient([FakeTool("search", result="ok")], hangs_on_close=True)
    session = build_session(client, close_timeout=0.1)
    session.start()

    started = time.monotonic()
    session.close()

    assert time.monotonic() - started < 5


def test_closing_a_session_that_was_never_opened_does_nothing():
    """Verify that closing a session that was never opened does nothing."""
    session = build_session(FakeClient([]))

    session.close()


def test_closing_stops_the_thread_the_session_ran_on():
    """Verify that closing stops the thread the session ran on."""
    session = build_session(FakeClient([FakeTool("search", result="ok")]))
    session.start()
    names = {thread.name for thread in threading.enumerate()}
    assert "mcp-fake-server" in names

    session.close()

    for _ in range(50):
        if "mcp-fake-server" not in {thread.name for thread in threading.enumerate()}:
            return
        threading.Event().wait(0.1)

    raise AssertionError("the session's loop thread outlived close()")


def test_a_closed_session_opens_a_new_one_when_called_again(closing):
    """Verify that a closed session opens a new one when called again."""
    client = FakeClient([FakeTool("search", result="ok")])
    session = build_session(client)
    closing(session)

    session.start()
    session.close()
    session.call_tool("search")

    assert client.opened == 2
