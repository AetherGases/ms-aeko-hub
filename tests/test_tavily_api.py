"""Verify Tavily Python SDK tool behavior and error handling."""

import pytest
from langchain_core.tools import Tool

from cmd.api.integrations import tavily_api


class FakeTavilyClient:
    """Records TavilyClient construction and method calls."""

    instances = []

    def __init__(self, api_key=None, **kwargs):
        self.api_key = api_key
        self.search_calls = []
        self.map_calls = []
        FakeTavilyClient.instances.append(self)

    def search(self, query, **kwargs):
        """Record a search call and return scripted search results."""
        self.search_calls.append({"query": query, **kwargs})
        return {"query": query, **kwargs}

    def map(self, url, **kwargs):
        """Record a map call and return scripted map results."""
        self.map_calls.append({"url": url, **kwargs})
        return {"url": url, **kwargs}


@pytest.fixture(autouse=True)
def reset_fake_client():
    """Reset recorded Tavily client instances before each test."""
    FakeTavilyClient.instances = []
    yield


@pytest.fixture(autouse=True)
def patch_tavily_client(monkeypatch):
    """Replace TavilyClient with a test double."""
    monkeypatch.setattr(tavily_api, "TavilyClient", FakeTavilyClient)
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")


def test_tavily_search_calls_client_search_with_the_query():
    """Verify that tavily search calls client search with the query."""
    result = tavily_api._tavily_search("What is the answer?")

    client = FakeTavilyClient.instances[-1]
    assert client.api_key == "test-key"
    assert result == {"query": "What is the answer?"}
    assert client.search_calls == [{"query": "What is the answer?"}]


def test_tavily_research_calls_client_search_with_advanced_depth():
    """Verify that tavily research uses advanced search depth."""
    result = tavily_api._tavily_research("scope 3 emissions benchmarks")

    client = FakeTavilyClient.instances[-1]
    assert result == {
        "query": "scope 3 emissions benchmarks",
        "search_depth": "advanced",
    }
    assert client.search_calls == [
        {"query": "scope 3 emissions benchmarks", "search_depth": "advanced"}
    ]


def test_tavily_map_maps_the_site_from_the_env_var(monkeypatch):
    """Verify that tavily map maps the site from the env var."""
    monkeypatch.setenv("AETHER_WEB_SITE_URL", "https://aether.example.com")

    result = tavily_api._tavily_map_aether_site()

    client = FakeTavilyClient.instances[-1]
    assert result == {"url": "https://aether.example.com"}
    assert client.map_calls == [{"url": "https://aether.example.com"}]


def test_tavily_map_ignores_whatever_input_the_agent_passes(monkeypatch):
    """Verify that tavily map ignores whatever input the agent passes."""
    monkeypatch.setenv("AETHER_WEB_SITE_URL", "https://aether.example.com")

    tavily_api._tavily_map_aether_site("some unrelated agent input")

    client = FakeTavilyClient.instances[-1]
    assert client.map_calls == [{"url": "https://aether.example.com"}]


def test_tavily_search_raises_when_no_tavily_api_key_is_available(monkeypatch):
    """Verify that tavily search raises when no tavily api key is available."""
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="TAVILY_API_KEY"):
        tavily_api._tavily_search("anything")


def test_get_tavily_search_tools_returns_search_and_research():
    """Verify that get tavily search tools returns search and research."""
    tools = tavily_api.get_tavily_search_tools()

    assert [tool.name for tool in tools] == ["tavily_search", "tavily_research"]
    assert all(isinstance(tool, Tool) for tool in tools)
    assert all(tool.description for tool in tools)


def test_get_tavily_search_tools_search_entry_is_backed_by_tavily_search():
    """Verify that get tavily search tools search entry is backed by tavily search."""
    tool = next(
        t for t in tavily_api.get_tavily_search_tools() if t.name == "tavily_search"
    )

    assert tool.func("query") == {"query": "query"}


def test_get_tavily_search_tools_research_entry_is_backed_by_tavily_research():
    """Verify that get tavily search tools research entry is backed by tavily research."""
    tool = next(
        t for t in tavily_api.get_tavily_search_tools() if t.name == "tavily_research"
    )

    assert tool.func("query") == {"query": "query", "search_depth": "advanced"}


def test_get_tavily_site_map_tool_returns_a_single_map_tool():
    """Verify that get tavily site map tool returns a single map tool."""
    tools = tavily_api.get_tavily_site_map_tool()

    assert len(tools) == 1
    assert isinstance(tools[0], Tool)
    assert tools[0].name == "tavily_map"
    assert tools[0].description


def test_get_tavily_site_map_tool_is_backed_by_the_pinned_site(monkeypatch):
    """Verify that get tavily site map tool is backed by the pinned site."""
    monkeypatch.setenv("AETHER_WEB_SITE_URL", "https://aether.example.com")

    tool = tavily_api.get_tavily_site_map_tool()[0]
    result = tool.func("")

    assert result == {"url": "https://aether.example.com"}
    client = FakeTavilyClient.instances[-1]
    assert client.map_calls == [{"url": "https://aether.example.com"}]
