"""Expose typed read-only MongoDB lookups for plans, users, memories, and sessions.

Tools read through domain services. The server selects the database at startup.
"""

from typing import Any

from langchain_core.tools import BaseTool, StructuredTool, create_schema_from_function

from cmd.api.acl.open_ai.wrappers import wrap_chatgpt_tools
from internal.shared import Module, logged

from cmd.api.tools.constants import (
    GET_IMPROVEMENT_PLAN_BY_INVENTORY_DESCRIPTION,
    GET_IMPROVEMENT_PLAN_PROBLEM_DESCRIPTION,
    GET_IMPROVEMENT_PLAN_METHOD_DESCRIPTION,
    GET_IMPROVEMENT_PLAN_REASONING_DESCRIPTION,
    LIST_LATEST_IMPROVEMENT_PLANS_DESCRIPTION,
    GET_USER_PROFILE_BY_EXTERNAL_ID_DESCRIPTION,
    UPDATE_USER_PROFILE_DESCRIPTION,
    LIST_USER_MEMORY_FIELDS_DESCRIPTION,
    GET_USER_MEMORY_BY_FIELD_DESCRIPTION,
    LIST_USER_MEMORIES_DESCRIPTION,
    LIST_USER_SESSION_NAMES_DESCRIPTION,
    GET_SESSION_MESSAGES_BY_NAME_DESCRIPTION,
    GET_LATEST_SESSION_MESSAGES_DESCRIPTION,
    COUNT_USER_SESSIONS_DESCRIPTION,
    MAX_LATEST_IMPROVEMENT_PLANS,
)

from improvement_plan.entity import ImprovementPlan
from session.entity import Message, Session
from user.entity import User, UserMemory


_plan_catalog_keys = (
    "id_external_inventory",
    "defined_problem",
    "method",
    "reasoning",
    "updated_at",
)

_message_catalog_keys = ("input", "output", "submitted_at")

_improvement_plans = None
_users = None
_sessions = None


def configure(*, improvement_plans=None, users=None, sessions=None) -> None:
    """Bind the domain services the Mongo tools read from."""

    global _improvement_plans, _users, _sessions
    _improvement_plans = improvement_plans
    _users = users
    _sessions = sessions


def _plans():
    """Return the configured improvement-plan service."""

    if _improvement_plans is None:
        raise RuntimeError("Improvement plan service is not configured.")
    return _improvement_plans


def _user_service():
    """Return the configured user service."""

    if _users is None:
        raise RuntimeError("User service is not configured.")
    return _users


def _session_service():
    """Return the configured session service."""

    if _sessions is None:
        raise RuntimeError("Session service is not configured.")
    return _sessions


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


def _required_text(value: Any, field_name: str) -> str:
    """Accept a nonempty string after trimming surrounding whitespace."""

    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a nonempty string.")

    stripped = value.strip()
    if stripped == "":
        raise ValueError(f"{field_name} must be a nonempty string.")

    return stripped


def _pick_keys(document: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    """Keep only the catalog output keys from a document."""

    return {key: document[key] for key in keys if key in document}


def _timestamp(value: Any) -> Any:
    """Render a datetime as ISO-8601 text, leaving other values unchanged."""

    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return isoformat()
    return value


def _plan_document(plan: ImprovementPlan) -> dict[str, Any]:
    """Render an improvement plan as a catalog document."""

    return {
        "id_external_inventory": plan.id_external_inventory,
        "defined_problem": plan.defined_problem,
        "method": plan.method,
        "reasoning": plan.reasoning,
        "updated_at": _timestamp(plan.updated_at),
    }


def _plan_catalog(
    plan: ImprovementPlan, keys: tuple[str, ...] = _plan_catalog_keys
) -> dict[str, Any]:
    """Keep only the requested catalog fields of an improvement plan."""

    return _pick_keys(_plan_document(plan), keys)


def _memory_document(memory: UserMemory) -> dict[str, Any]:
    """Render a user memory as a catalog document."""

    return {"field": memory.field, "description": memory.description}


def _message_document(message: Message) -> dict[str, Any]:
    """Render a session message as a catalog document."""

    return {
        "input": message.input,
        "output": message.output,
        "submitted_at": _timestamp(message.submitted_at),
    }


def _newest_first(
    documents: list[dict[str, Any]], field_name: str
) -> list[dict[str, Any]]:
    """Order documents by a timestamp field, newest first."""

    return sorted(documents, key=lambda item: item.get(field_name) or "", reverse=True)


def _require_user(id_external_user: Any) -> User:
    """Resolve an external user identifier through the user service."""

    identifier = _positive_int(id_external_user, "id_external_user")
    return _user_service().get_mongo_user(identifier)


def _valid_memories(user: User) -> list[UserMemory]:
    """Return the user's memories that have not expired."""

    return [
        memory
        for memory in _user_service().get_user_memories(user.id)
        if memory.is_valid()
    ]


def _user_sessions(user: User) -> list[Session]:
    """List a user's sessions, treating an empty store as no sessions."""

    try:
        return list(_session_service().get_user_sessions(user.id))
    except ValueError:
        return []


def _session_named(user: User, session_name: str) -> Session:
    """Return the user's session with the supplied name, or raise if it is missing."""

    for session in _user_sessions(user):
        if session.name == session_name:
            return session
    raise ValueError(f"No session found for session_name {session_name}.")


def _plan_by_inventory(
    id_external_inventory: Any, keys: tuple[str, ...]
) -> list[dict[str, Any]]:
    """Load one inventory plan through the service and keep the requested fields."""

    identifier = _positive_int(id_external_inventory, "id_external_inventory")
    plan = _plans().get_by_id_external_inventory(identifier)
    return [_plan_catalog(plan, keys)]


@logged(Module.TOOL, "get_improvement_plan_by_inventory")
def _get_improvement_plan_by_inventory(
    id_external_inventory: int,
) -> list[dict[str, Any]]:
    """Return the improvement plan for an external inventory identifier."""

    return _plan_by_inventory(id_external_inventory, _plan_catalog_keys)


@logged(Module.TOOL, "get_improvement_plan_problem")
def _get_improvement_plan_problem(id_external_inventory: int) -> list[dict[str, Any]]:
    """Return the defined problem for an inventory's improvement plan."""

    return _plan_by_inventory(
        id_external_inventory, ("id_external_inventory", "defined_problem")
    )


@logged(Module.TOOL, "get_improvement_plan_method")
def _get_improvement_plan_method(id_external_inventory: int) -> list[dict[str, Any]]:
    """Return the method for an inventory's improvement plan."""

    return _plan_by_inventory(
        id_external_inventory, ("id_external_inventory", "method")
    )


@logged(Module.TOOL, "get_improvement_plan_reasoning")
def _get_improvement_plan_reasoning(id_external_inventory: int) -> list[dict[str, Any]]:
    """Return the reasoning for an inventory's improvement plan."""

    return _plan_by_inventory(
        id_external_inventory, ("id_external_inventory", "reasoning")
    )


def _company_id(user: User) -> int:
    """Resolve the user's company, rejecting a missing or non-positive value."""

    company = user.id_external_company
    if company is None:
        raise ValueError("id_external_company is required to search improvement plans.")
    return _positive_int(company, "id_external_company")


@logged(Module.TOOL, "list_latest_improvement_plans")
def _list_latest_improvement_plans(
    id_external_user: int, n: int
) -> list[dict[str, Any]]:
    """Return the n most recently updated improvement plans for the user's company."""

    user = _require_user(id_external_user)
    company = _company_id(user)
    limit = _positive_int(n, "n")
    if limit > MAX_LATEST_IMPROVEMENT_PLANS:
        raise ValueError(f"n must be at most {MAX_LATEST_IMPROVEMENT_PLANS}.")
    documents = [_plan_catalog(plan) for plan in _plans().list_latest(limit, company)]
    return _newest_first(documents, "updated_at")[:limit]


def _assert_profile_subject(id_external_user: int) -> None:
    """Reject profile reads when identity is unbound or does not match the subject."""

    from cmd.api.acl.open_ai.identity import current_id_external_user

    bound = current_id_external_user()
    if bound != id_external_user:
        raise ValueError("id_external_user does not match the OAuth token.")


@logged(Module.TOOL, "get_user_profile_by_external_id")
def _get_user_profile_by_external_id(id_external_user: int) -> dict[str, Any]:
    """Return the ms-auth profile merged with ChatGPT role and usecase."""

    from cmd.api.acl.open_ai.identity import current_ms_auth_profile
    from cmd.api.integrations.profile_api import profile_id, profile_tool_catalog

    identifier = _positive_int(id_external_user, "id_external_user")
    _assert_profile_subject(identifier)
    user = _require_user(identifier)
    try:
        ms_profile = current_ms_auth_profile()
    except RuntimeError as exc:
        raise ValueError("Sign in is required to read the user profile.") from exc
    if profile_id(ms_profile) != identifier:
        raise ValueError("id_external_user does not match the ms-auth profile.")
    return profile_tool_catalog(
        ms_profile,
        role=user.role,
        usecase=user.usecase,
    )


@logged(Module.TOOL, "list_user_memories")
def _list_user_memories(id_external_user: int) -> list[dict[str, Any]]:
    """List unexpired memory field and description pairs for an external user."""

    user = _require_user(id_external_user)
    return [
        _pick_keys(_memory_document(memory), ("field", "description"))
        for memory in _valid_memories(user)
    ]


@logged(Module.TOOL, "list_user_memory_fields")
def _list_user_memory_fields(id_external_user: int) -> list[dict[str, Any]]:
    """List unexpired memory field names for an external user."""

    user = _require_user(id_external_user)
    return [
        _pick_keys(_memory_document(memory), ("field",))
        for memory in _valid_memories(user)
    ]


@logged(Module.TOOL, "get_user_memory_by_field")
def _get_user_memory_by_field(id_external_user: int, field: str) -> dict[str, Any]:
    """Return one unexpired memory's field and description for an external user."""

    identifier = _positive_int(id_external_user, "id_external_user")
    field_name = _required_text(field, "field")
    user = _require_user(identifier)
    for memory in _valid_memories(user):
        if memory.field == field_name:
            return _pick_keys(_memory_document(memory), ("field", "description"))
    raise ValueError(f"No memory found for field {field_name}.")


@logged(Module.TOOL, "list_user_session_names")
def _list_user_session_names(id_external_user: int) -> list[dict[str, Any]]:
    """List conversation session names for an external user."""

    user = _require_user(id_external_user)
    return [{"name": session.name} for session in _user_sessions(user)]


@logged(Module.TOOL, "get_session_messages_by_name")
def _get_session_messages_by_name(
    id_external_user: int,
    session_name: str,
) -> list[dict[str, Any]]:
    """Return messages from one named session belonging to an external user."""

    identifier = _positive_int(id_external_user, "id_external_user")
    name = _required_text(session_name, "session_name")
    user = _require_user(identifier)
    session = _session_named(user, name)
    return [
        _pick_keys(_message_document(message), _message_catalog_keys)
        for message in _session_service().get_session_messages(session.id)
    ]


@logged(Module.TOOL, "get_latest_session_messages")
def _get_latest_session_messages(
    id_external_user: int,
    session_name: str,
    n: int,
) -> list[dict[str, Any]]:
    """Return the n most recent messages from one named session."""

    identifier = _positive_int(id_external_user, "id_external_user")
    name = _required_text(session_name, "session_name")
    limit = _positive_int(n, "n")
    user = _require_user(identifier)
    session = _session_named(user, name)
    documents = [
        _pick_keys(_message_document(message), _message_catalog_keys)
        for message in _session_service().get_session_messages(session.id)
    ]
    return _newest_first(documents, "submitted_at")[:limit]


@logged(Module.TOOL, "count_user_sessions")
def _count_user_sessions(id_external_user: int) -> dict[str, int]:
    """Count conversation sessions belonging to an external user."""

    user = _require_user(id_external_user)
    return {"count": len(_user_sessions(user))}


@logged(Module.TOOL, "update_user_profile")
def _update_user_profile(
    id_external_user: int,
    role: str | None = None,
    usecase: str | None = None,
) -> dict[str, Any]:
    """Update role and/or usecase for an existing Mongo user."""

    identifier = _positive_int(id_external_user, "id_external_user")
    update_role = _required_text(role, "role") if role is not None else None
    update_usecase = _required_text(usecase, "usecase") if usecase is not None else None
    user = _user_service().update_user_profile(
        identifier,
        role=update_role,
        usecase=update_usecase,
    )
    return {
        "id_external_user": user.id_external_user,
        "role": user.role,
        "usecase": user.usecase,
    }


def _typed_tool(name: str, description: str, func: Any) -> StructuredTool:
    """Build a StructuredTool whose schema uses the function's named arguments."""

    return StructuredTool.from_function(
        name=name,
        description=description,
        func=func,
        args_schema=create_schema_from_function(name, func),
    )


def get_improvement_plan_tools() -> list[BaseTool]:
    """Return typed plan tools that inject bound identity and hide other companies."""

    return wrap_chatgpt_tools(
        [
            _typed_tool(
                "get_improvement_plan_by_inventory",
                GET_IMPROVEMENT_PLAN_BY_INVENTORY_DESCRIPTION,
                _get_improvement_plan_by_inventory,
            ),
            _typed_tool(
                "get_improvement_plan_problem",
                GET_IMPROVEMENT_PLAN_PROBLEM_DESCRIPTION,
                _get_improvement_plan_problem,
            ),
            _typed_tool(
                "get_improvement_plan_method",
                GET_IMPROVEMENT_PLAN_METHOD_DESCRIPTION,
                _get_improvement_plan_method,
            ),
            _typed_tool(
                "get_improvement_plan_reasoning",
                GET_IMPROVEMENT_PLAN_REASONING_DESCRIPTION,
                _get_improvement_plan_reasoning,
            ),
            _typed_tool(
                "list_latest_improvement_plans",
                LIST_LATEST_IMPROVEMENT_PLANS_DESCRIPTION,
                _list_latest_improvement_plans,
            ),
        ]
    )


def get_user_memory_tools() -> list[BaseTool]:
    """Return typed user and memory tools that inject bound conversation identity."""

    return wrap_chatgpt_tools(
        [
            _typed_tool(
                "get_user_profile_by_external_id",
                GET_USER_PROFILE_BY_EXTERNAL_ID_DESCRIPTION,
                _get_user_profile_by_external_id,
            ),
            _typed_tool(
                "list_user_memory_fields",
                LIST_USER_MEMORY_FIELDS_DESCRIPTION,
                _list_user_memory_fields,
            ),
            _typed_tool(
                "get_user_memory_by_field",
                GET_USER_MEMORY_BY_FIELD_DESCRIPTION,
                _get_user_memory_by_field,
            ),
            _typed_tool(
                "list_user_memories",
                LIST_USER_MEMORIES_DESCRIPTION,
                _list_user_memories,
            ),
        ]
    )


def get_user_profile_write_tools() -> list[BaseTool]:
    """Return typed profile writers that inject bound conversation identity."""

    return wrap_chatgpt_tools(
        [
            _typed_tool(
                "update_user_profile",
                UPDATE_USER_PROFILE_DESCRIPTION,
                _update_user_profile,
            ),
        ]
    )


def get_session_tools() -> list[BaseTool]:
    """Return typed session tools that inject bound conversation identity."""

    return wrap_chatgpt_tools(
        [
            _typed_tool(
                "list_user_session_names",
                LIST_USER_SESSION_NAMES_DESCRIPTION,
                _list_user_session_names,
            ),
            _typed_tool(
                "get_session_messages_by_name",
                GET_SESSION_MESSAGES_BY_NAME_DESCRIPTION,
                _get_session_messages_by_name,
            ),
            _typed_tool(
                "get_latest_session_messages",
                GET_LATEST_SESSION_MESSAGES_DESCRIPTION,
                _get_latest_session_messages,
            ),
            _typed_tool(
                "count_user_sessions",
                COUNT_USER_SESSIONS_DESCRIPTION,
                _count_user_sessions,
            ),
        ]
    )
