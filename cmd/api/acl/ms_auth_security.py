"""Resolve ms-auth Bearer tokens through GET /api/profile."""

import hashlib
import json
from typing import NamedTuple

from cmd.api.acl.constants import _PROFILE_CACHE_TTL_SECONDS
from cmd.api.integrations.profile_api import (
    ProfileError,
    get_profile,
    profile_enterprise_id,
    profile_id,
)


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


def _profile_cache_key(access_token: str) -> str:
    """Build the Redis key used to cache a resolved principal."""
    digest = hashlib.sha256(access_token.encode("utf-8")).hexdigest()
    return f"msauth:profile:{digest}"


def _read_cached_principal(redis_client, cache_key: str, access_token: str):
    """Return a cached principal document, or None."""
    try:
        payload = redis_client.get(cache_key)
    except Exception:
        return None
    if payload is None:
        return None
    try:
        decoded = payload.decode() if isinstance(payload, bytes) else payload
        document = json.loads(decoded)
        return MsAuthPrincipal(
            access_token=access_token,
            id_external_user=int(document["id_external_user"]),
            id_external_company=int(document["id_external_company"]),
            profile=document["profile"],
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _write_cached_principal(
    redis_client, cache_key: str, principal: MsAuthPrincipal
) -> None:
    """Store a resolved principal in Redis for the cache TTL."""
    try:
        redis_client.set(
            cache_key,
            json.dumps(
                {
                    "id_external_user": principal.id_external_user,
                    "id_external_company": principal.id_external_company,
                    "profile": principal.profile,
                }
            ),
            ex=_PROFILE_CACHE_TTL_SECONDS,
        )
    except Exception:
        return


def resolve_ms_auth_access_token_cached(
    access_token: str, redis_client=None
) -> MsAuthPrincipal:
    """Return a Redis-cached principal or validate the token with ms-auth."""
    token = (access_token or "").strip()
    if not token:
        raise ValueError("Missing access token.")
    if redis_client is not None:
        cache_key = _profile_cache_key(token)
        cached = _read_cached_principal(redis_client, cache_key, token)
        if cached is not None:
            return cached
    principal = resolve_ms_auth_access_token(token)
    if redis_client is not None:
        _write_cached_principal(redis_client, _profile_cache_key(token), principal)
    return principal
