"""Assemble the tool catalog exposed to ChatGPT.

The catalog is the union of the tools already used by the Aeko agents plus the
ChatGPT-only tools. Metrics and Chroma write tools are never part of it.
Tavily stays on Aeko agents and is omitted here.
"""

from langchain_core.tools import Tool

from cmd.api.acl.open_ai.wrappers import wrap_chatgpt_tools
from cmd.api.integrations.climatiq_api import get_climatiq_tools
from cmd.api.integrations.mcp.chroma_mcp import (
    get_gases_info_tools,
    get_improvement_plan_problem_tools,
)
from cmd.api.tools.ask_aeko import get_ask_aeko_tools
from cmd.api.tools.calculator import get_calculator_tools
from cmd.api.tools.finance import get_roi_payback_tools
from cmd.api.tools.inventory_tools import get_inventory_ingest_tools
from cmd.api.tools.mongo_tools import (
    get_improvement_plan_tools,
    get_session_tools,
    get_user_memory_tools,
)

_CATALOG_GETTERS = (
    get_improvement_plan_tools,
    get_improvement_plan_problem_tools,
    get_user_memory_tools,
    get_session_tools,
    get_gases_info_tools,
    get_climatiq_tools,
    get_calculator_tools,
    get_roi_payback_tools,
    get_inventory_ingest_tools,
    get_ask_aeko_tools,
)


def get_chatgpt_tools() -> list[Tool]:
    """Return every tool exposed to ChatGPT, unique by tool name."""

    tools: dict[str, Tool] = {}
    for getter in _CATALOG_GETTERS:
        for tool in getter():
            tools.setdefault(tool.name, tool)
    return wrap_chatgpt_tools(list(tools.values()))


def chatgpt_tool_names() -> set[str]:
    """Return the names of the tools exposed to ChatGPT."""

    return {tool.name for tool in get_chatgpt_tools()}
