"""Resolve ms-auth Bearer tokens through GET /api/profile."""

import hashlib
import time
from threading import Lock
from typing import NamedTuple

from cmd.api.integrations.profile_api import (
    ProfileError,
    get_profile,
    profile_enterprise_id,
    profile_id,
)

_PROFILE_CACHE_TTL_SECONDS = 30
_profile_cache: dict[str, tuple[float, "MsAuthPrincipal"]] = {}
_profile_cache_lock = Lock()


class MsAuthPrincipal(NamedTuple):
    """Identity established from a valid ms-auth access token."""

    access_token: str
    id_external_user: int
    id_external_company: int
    profile: dict


def parse_bearer_authorization(header: str | None) -> str | None:
    """Return the Bearer token from an Authorization header, if present."""
    if not header:
        return None
    scheme, _, credentials = header.partition(" ")
    if scheme.lower() != "bearer" or not credentials.strip():
        return None
    return credentials.strip()


def resolve_ms_auth_access_token(access_token: str) -> MsAuthPrincipal:
    """Validate the token with ms-auth and return the caller identity."""
    token = (access_token or "").strip()
    if not token:
        raise ValueError("Missing access token.")
    try:
        profile = get_profile(token)
    except ProfileError as exc:
        raise ValueError("Invalid or expired access token.") from exc
    return MsAuthPrincipal(
        access_token=token,
        id_external_user=profile_id(profile),
        id_external_company=profile_enterprise_id(profile),
        profile=profile,
    )


def resolve_ms_auth_access_token_cached(access_token: str) -> MsAuthPrincipal:
    """Return a cached principal or validate the token with ms-auth."""
    token = (access_token or "").strip()
    if not token:
        raise ValueError("Missing access token.")
    cache_key = hashlib.sha256(token.encode("utf-8")).hexdigest()
    now = time.monotonic()
    with _profile_cache_lock:
        cached = _profile_cache.get(cache_key)
        if cached is not None and cached[0] > now:
            return cached[1]
        _profile_cache.pop(cache_key, None)
    principal = resolve_ms_auth_access_token(token)
    with _profile_cache_lock:
        _profile_cache[cache_key] = (now + _PROFILE_CACHE_TTL_SECONDS, principal)
    return principal
