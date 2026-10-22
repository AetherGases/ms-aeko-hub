"""Expose Tavily search, research, and a site map restricted to the configured URL."""

import os
from typing import Any

from langchain_core.tools import Tool
from tavily import TavilyClient

from cmd.api.integrations.mcp.constants import (
    TAVILY_MAP_DESCRIPTION,
    TAVILY_RESEARCH_DESCRIPTION,
    TAVILY_SEARCH_DESCRIPTION,
)
from internal.shared import Module, logged


def _api_key(api_key: str | None = None) -> str:
    """Resolve the Tavily credential from the argument or environment and reject an empty key."""

    if api_key is None:
        api_key = os.environ.get("TAVILY_API_KEY", "")

    if api_key == "":
        raise RuntimeError(
            "TAVILY_API_KEY is not set. Please set it in the environment or pass it to _client()."
        )

    return api_key


def _client(api_key: str | None = None) -> TavilyClient:
    """Build a Tavily client using the resolved API key."""

    return TavilyClient(api_key=_api_key(api_key))


@logged(Module.TOOL, "tavily_search")
def _tavily_search(query: str) -> Any:
    """Run a Tavily web search and return serialized results."""
    return _client().search(query)


@logged(Module.TOOL, "tavily_research")
def _tavily_research(query: str) -> Any:
    """Run a Tavily research query and return serialized results."""
    return _client().search(query, search_depth="advanced")


@logged(Module.TOOL, "tavily_map")
def _tavily_map_aether_site(_input: str = "") -> Any:
    """Map the Aether URL from the environment without accepting an agent-supplied URL."""

    site_url = os.environ.get("AETHER_WEB_SITE_URL", "")
    return _client().map(site_url)


def get_tavily_search_tools() -> list[Tool]:
    """Return Tavily web search and research tools."""

    return [
        Tool(
            name="tavily_search",
            description=TAVILY_SEARCH_DESCRIPTION,
            func=_tavily_search,
        ),
        Tool(
            name="tavily_research",
            description=TAVILY_RESEARCH_DESCRIPTION,
            func=_tavily_research,
        ),
    ]


def get_tavily_site_map_tool() -> list[Tool]:
    """Return a Tavily site-map tool restricted to the configured Aether URL."""

    return [
        Tool(
            name="tavily_map",
            description=TAVILY_MAP_DESCRIPTION,
            func=_tavily_map_aether_site,
        ),
    ]
