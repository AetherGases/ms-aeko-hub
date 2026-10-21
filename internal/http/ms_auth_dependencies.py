"""FastAPI dependencies that require a valid ms-auth Bearer token."""

from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool

from cmd.api.acl.ms_auth_security import (
    MsAuthPrincipal,
    parse_bearer_authorization,
    resolve_ms_auth_access_token_cached,
)
from cmd.api.acl.open_ai.identity import (
    bind_id_external_company,
    bind_id_external_user,
    bind_ms_auth_access_token,
    bind_ms_auth_profile,
    reset_id_external_company,
    reset_id_external_user,
    reset_ms_auth_access_token,
    reset_ms_auth_profile,
)


async def require_ms_auth_principal(request: Request):
    """Validate the Authorization header and bind identity for the request."""
    token = parse_bearer_authorization(request.headers.get("Authorization"))
    if token is None:
        raise HTTPException(status_code=401, detail="Missing access token.")
    try:
        principal = await run_in_threadpool(resolve_ms_auth_access_token_cached, token)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    user_token = bind_id_external_user(principal.id_external_user)
    company_token = bind_id_external_company(principal.id_external_company)
    access_token = bind_ms_auth_access_token(principal.access_token)
    profile_token = bind_ms_auth_profile(principal.profile)
    request.state.ms_auth_principal = principal
    try:
        yield principal
    finally:
        reset_ms_auth_profile(profile_token)
        reset_ms_auth_access_token(access_token)
        reset_id_external_company(company_token)
        reset_id_external_user(user_token)


MsAuth = Annotated[MsAuthPrincipal, Depends(require_ms_auth_principal)]
