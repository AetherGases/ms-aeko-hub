"""Expose greenhouse-gas vector searches through a persistent Chroma MCP session.

The child process receives credentials and model cache settings through its
environment. Progress bars are disabled to avoid filling the stderr pipe.
"""

import os
import sys
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool, Tool, create_schema_from_function
from langchain_mcp_adapters.client import MultiServerMCPClient

from .mcp_session import PersistentMCPSession

from internal.shared import Module, logged

from cmd.api.integrations.mcp.constants import (
    QUERY_GASES_INFO_TOOL_NAME,
    CHROMA_MCP_SERVER_SCRIPT,
    PASSTHROUGH_ENV_VARS,
    QUIET_CHILD_ENV,
    QUERY_GASES_INFO_DESCRIPTION,
    QUERY_IMPROVEMENT_PLAN_PROBLEMS_TOOL_NAME,
    QUERY_IMPROVEMENT_PLAN_PROBLEMS_DESCRIPTION,
)


def _required_setting(value: str | None, env_var: str) -> str:
    """Resolve a required Chroma Cloud setting and reject an empty value."""

    if value is None:
        value = os.environ.get(env_var, "")

    if value == "":
        raise RuntimeError(
            f"{env_var} is not set. Please set it in the environment or pass it to _configure_mcp_client()."
        )

    return value


def _server_environment(tenant: str, database: str, api_key: str) -> dict[str, str]:
    """Build the child environment with credentials, cache paths, and quiet progress settings."""

    environment = {
        "CHROMA_TENANT": tenant,
        "CHROMA_DATABASE": database,
        "CHROMA_API_KEY": api_key,
        **QUIET_CHILD_ENV,
    }
    for name in PASSTHROUGH_ENV_VARS:
        value = os.environ.get(name)
        if value is not None:
            environment[name] = value

    return environment


def _configure_mcp_client(
    tenant: str | None = None,
    database: str | None = None,
    api_key: str | None = None,
) -> MultiServerMCPClient:
    """Build the configured stdio MCP client, validating required credentials."""

    tenant = _required_setting(tenant, "CHROMA_TENANT")
    database = _required_setting(database, "CHROMA_DATABASE")
    api_key = _required_setting(api_key, "CHROMA_API_KEY")

    return MultiServerMCPClient(
        {
            "chroma": {
                "transport": "stdio",
                "command": sys.executable,
                "args": [str(CHROMA_MCP_SERVER_SCRIPT)],
                "env": _server_environment(tenant, database, api_key),
            }
        }
    )


CHROMA_SESSION = PersistentMCPSession("chroma", lambda: _configure_mcp_client())

_users = None
_improvement_plans = None


def configure(*, users=None, improvement_plans=None) -> None:
    """Bind the user and improvement-plan services the agent wrapper reads."""

    global _users, _improvement_plans
    _users = users
    _improvement_plans = improvement_plans


def _user_service():
    """Return the configured user service."""

    if _users is None:
        raise RuntimeError("User service is not configured.")
    return _users


def _plan_service():
    """Return the configured improvement-plan service."""

    if _improvement_plans is None:
        raise RuntimeError("Improvement plan service is not configured.")
    return _improvement_plans


def _positive_int(value: Any, field_name: str) -> int:
    """Accept a positive integer or numeric string and reject bools or other values."""

    if isinstance(value, bool) or value is None:
        raise ValueError(f"{field_name} must be a positive integer.")

    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str):
        stripped = value.strip()
        if stripped == "" or not stripped.isdigit():
            raise ValueError(f"{field_name} must be a positive integer.")
        parsed = int(stripped)
    else:
        raise ValueError(f"{field_name} must be a positive integer.")

    if parsed <= 0:
        raise ValueError(f"{field_name} must be a positive integer.")

    return parsed


def _timestamp(value: Any) -> Any:
    """Render a datetime as ISO-8601 text, leaving other values unchanged."""

    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return isoformat()
    return value


def _plan_document(plan: Any) -> dict[str, Any]:
    """Render an improvement plan as a catalog document without company."""

    return {
        "id_external_inventory": plan.id_external_inventory,
        "defined_problem": plan.defined_problem,
        "method": plan.method,
        "reasoning": plan.reasoning,
        "updated_at": _timestamp(plan.updated_at),
    }


def _metadata_row(payload: Any) -> list[Any]:
    """Return the first metadata row from a Chroma query payload."""

    metadatas = (payload or {}).get("metadatas") or [[]]
    if not isinstance(metadatas, list) or metadatas == []:
        return []

    first_row = metadatas[0]
    if isinstance(first_row, dict):
        return [first_row]
    if isinstance(first_row, list):
        return first_row
    return []


def _company_id(user: Any) -> int:
    """Resolve the user's company, rejecting a missing or non-positive value."""

    company = user.id_external_company
    if company in (None,):
        raise ValueError("id_external_company is required to search improvement plans.")

    return _positive_int(company, "id_external_company")


def _call_chroma_tool(tool_name: str, **kwargs: Any) -> Any:
    """Invoke a Chroma tool synchronously through the shared MCP session."""

    return CHROMA_SESSION.call_tool(tool_name, **kwargs)


def _parse_query(query: str | list[str] | None) -> list[str]:
    """Normalize a search string or list to nonempty query texts, rejecting invalid entries."""

    if isinstance(query, str):
        candidates = [query]
    elif isinstance(query, list):
        candidates = query
    else:
        candidates = []

    texts = [
        text.strip()
        for text in candidates
        if isinstance(text, str) and text.strip() != ""
    ]

    if len(texts) != len(candidates) or texts == []:
        raise ValueError(
            f"Query must be a non-empty search text, or a list of them, got {query!r}."
        )

    return texts


@logged(Module.TOOL, "query_gases_info")
def _query_gases_info(query: str | list[str] | None = "") -> Any:
    """Search the pinned greenhouse-gas collection with validated query texts."""

    return _call_chroma_tool(
        QUERY_GASES_INFO_TOOL_NAME,
        query_texts=_parse_query(query),
    )


def get_gases_info_tools() -> list[Tool]:
    """Return the greenhouse-gas knowledge base search tool."""

    return [
        Tool(
            name="query_gases_info",
            description=QUERY_GASES_INFO_DESCRIPTION,
            func=_query_gases_info,
        ),
    ]


def _hydrate_plans(payload: Any, company: int) -> list[dict[str, Any]]:
    """Load Mongo plans for Chroma hits and drop other companies or missing rows."""

    plans = _plan_service()
    documents: list[dict[str, Any]] = []
    for metadata in _metadata_row(payload):
        if not isinstance(metadata, dict) or "id_external_inventory" not in metadata:
            continue
        try:
            plan = plans.get_by_id_external_inventory(metadata["id_external_inventory"])
        except ValueError:
            continue
        if plan.id_external_company != company:
            continue
        documents.append(_plan_document(plan))
    return documents


@logged(Module.TOOL, "query_improvement_plan_problems")
def _query_improvement_plan_problems(
    id_external_user: int, query: str
) -> list[dict[str, Any]]:
    """Search plan problems in the user's company and return hydrated catalog rows."""

    identifier = _positive_int(id_external_user, "id_external_user")
    text = _parse_query(query)[0]
    user = _user_service().get_mongo_user(identifier)
    company = _company_id(user)
    payload = _call_chroma_tool(
        QUERY_IMPROVEMENT_PLAN_PROBLEMS_TOOL_NAME,
        query_texts=[text],
        id_external_company=company,
    )
    return _hydrate_plans(payload, company)


def _upsert_improvement_plan_problem(
    id_external_inventory: int,
    defined_problem: str,
    id_external_company: int,
) -> Any:
    """Index one defined problem through the Chroma MCP upsert tool."""

    return _call_chroma_tool(
        "upsert_improvement_plan_problem",
        id_external_inventory=id_external_inventory,
        defined_problem=defined_problem,
        id_external_company=id_external_company,
    )


def _typed_tool(name: str, description: str, func: Any) -> StructuredTool:
    """Build a StructuredTool whose schema uses the function's named arguments."""

    return StructuredTool.from_function(
        name=name,
        description=description,
        func=func,
        args_schema=create_schema_from_function(name, func),
    )


def get_improvement_plan_problem_tools() -> list[BaseTool]:
    """Return the company-scoped improvement-plan problem search tool."""

    return [
        _typed_tool(
            QUERY_IMPROVEMENT_PLAN_PROBLEMS_TOOL_NAME,
            QUERY_IMPROVEMENT_PLAN_PROBLEMS_DESCRIPTION,
            _query_improvement_plan_problems,
        ),
    ]
