"""Bind ChatGPT OAuth identity on the current task with ContextVars."""

from contextvars import ContextVar

_id_external_user: ContextVar[int | None] = ContextVar("chatgpt_id_external_user", default=None)
_id_external_company: ContextVar[int | None] = ContextVar("chatgpt_id_external_company", default=None)
_ms_auth_access_token: ContextVar[str | None] = ContextVar("ms_auth_access_token", default=None)
_ms_auth_profile: ContextVar[dict | None] = ContextVar("ms_auth_profile", default=None)
_SCOPE_STATE_KEY = "chatgpt_id_external_user"
_SCOPE_STATE_COMPANY_KEY = "chatgpt_id_external_company"
_SCOPE_STATE_MS_AUTH_PROFILE_KEY = "chatgpt_ms_auth_profile"
_SCOPE_STATE_MS_AUTH_ACCESS_TOKEN_KEY = "chatgpt_ms_auth_access_token"


def bind_id_external_user(id_external_user: int):
    """Bind the ChatGPT user identifier for the current task."""
    return _id_external_user.set(id_external_user)


def reset_id_external_user(token) -> None:
    """Clear the ChatGPT user identifier bound by bind_id_external_user."""
    _id_external_user.reset(token)


def bind_id_external_company(id_external_company: int):
    """Bind the ChatGPT company identifier for the current task."""
    return _id_external_company.set(id_external_company)


def reset_id_external_company(token) -> None:
    """Clear the company identifier bound by bind_id_external_company."""
    _id_external_company.reset(token)


def bind_ms_auth_access_token(access_token: str):
    """Bind the ms-auth access token for the current task."""
    return _ms_auth_access_token.set(access_token)


def reset_ms_auth_access_token(token) -> None:
    """Clear the ms-auth access token bound by bind_ms_auth_access_token."""
    _ms_auth_access_token.reset(token)


def bind_ms_auth_profile(profile: dict):
    """Bind the ms-auth profile payload for the current task."""
    return _ms_auth_profile.set(profile)


def reset_ms_auth_profile(token) -> None:
    """Clear the ms-auth profile bound by bind_ms_auth_profile."""
    _ms_auth_profile.reset(token)


def current_ms_auth_access_token() -> str:
    """Return the bound ms-auth access token."""
    value = _ms_auth_access_token.get()
    if value is not None:
        return value
    attached = _ms_auth_access_token_from_mcp_request()
    if attached is not None:
        return attached
    raise RuntimeError("ms-auth access token is not bound.")


def current_ms_auth_profile() -> dict:
    """Return the bound ms-auth profile payload."""
    value = _ms_auth_profile.get()
    if value is not None:
        return value
    attached = _ms_auth_profile_from_mcp_request()
    if attached is not None:
        return attached
    raise RuntimeError("ms-auth profile is not bound.")


def attach_id_external_user(scope, id_external_user: int) -> None:
    """Store the ChatGPT user identifier on the ASGI scope for the MCP session."""
    state = scope.get("state")
    if isinstance(state, dict):
        state[_SCOPE_STATE_KEY] = id_external_user
        return
    if state is None:
        scope["state"] = {_SCOPE_STATE_KEY: id_external_user}
        return
    setattr(state, _SCOPE_STATE_KEY, id_external_user)


def attach_id_external_company(scope, id_external_company: int) -> None:
    """Store the ChatGPT company identifier on the ASGI scope for the MCP session."""
    state = scope.get("state")
    if isinstance(state, dict):
        state[_SCOPE_STATE_COMPANY_KEY] = id_external_company
        return
    if state is None:
        scope["state"] = {_SCOPE_STATE_COMPANY_KEY: id_external_company}
        return
    setattr(state, _SCOPE_STATE_COMPANY_KEY, id_external_company)


def attach_ms_auth_profile(scope, profile: dict) -> None:
    """Store the ms-auth profile on the ASGI scope for the MCP session."""
    state = scope.get("state")
    if isinstance(state, dict):
        state[_SCOPE_STATE_MS_AUTH_PROFILE_KEY] = profile
        return
    if state is None:
        scope["state"] = {_SCOPE_STATE_MS_AUTH_PROFILE_KEY: profile}
        return
    setattr(state, _SCOPE_STATE_MS_AUTH_PROFILE_KEY, profile)


def attach_ms_auth_access_token(scope, access_token: str) -> None:
    """Store the ms-auth access token on the ASGI scope for the MCP session."""
    state = scope.get("state")
    if isinstance(state, dict):
        state[_SCOPE_STATE_MS_AUTH_ACCESS_TOKEN_KEY] = access_token
        return
    if state is None:
        scope["state"] = {_SCOPE_STATE_MS_AUTH_ACCESS_TOKEN_KEY: access_token}
        return
    setattr(state, _SCOPE_STATE_MS_AUTH_ACCESS_TOKEN_KEY, access_token)


def current_id_external_user() -> int:
    """Return the bound ChatGPT user identifier."""
    value = _id_external_user.get()
    if value is not None:
        return value
    attached = _id_external_user_from_mcp_request()
    if attached is not None:
        return attached
    raise RuntimeError("ChatGPT identity is not bound.")


def current_id_external_company() -> int:
    """Return the bound ChatGPT company identifier."""
    value = _id_external_company.get()
    if value is not None:
        return value
    attached = _id_external_company_from_mcp_request()
    if attached is not None:
        return attached
    raise RuntimeError("ChatGPT company identity is not bound.")


def _id_external_user_from_mcp_request() -> int | None:
    try:
        from mcp.server.lowlevel.server import request_ctx

        request = request_ctx.get().request
    except LookupError:
        return None
    state = getattr(request, "state", None)
    value = getattr(state, _SCOPE_STATE_KEY, None)
    return value if isinstance(value, int) else None


def _id_external_company_from_mcp_request() -> int | None:
    try:
        from mcp.server.lowlevel.server import request_ctx

        request = request_ctx.get().request
    except LookupError:
        return None
    state = getattr(request, "state", None)
    value = getattr(state, _SCOPE_STATE_COMPANY_KEY, None)
    return value if isinstance(value, int) else None


def _ms_auth_profile_from_mcp_request() -> dict | None:
    try:
        from mcp.server.lowlevel.server import request_ctx

        request = request_ctx.get().request
    except LookupError:
        return None
    state = getattr(request, "state", None)
    value = getattr(state, _SCOPE_STATE_MS_AUTH_PROFILE_KEY, None)
    return value if isinstance(value, dict) else None


def _ms_auth_access_token_from_mcp_request() -> str | None:
    try:
        from mcp.server.lowlevel.server import request_ctx

        request = request_ctx.get().request
    except LookupError:
        return None
    state = getattr(request, "state", None)
    value = getattr(state, _SCOPE_STATE_MS_AUTH_ACCESS_TOKEN_KEY, None)
    return value if isinstance(value, str) and value else None
