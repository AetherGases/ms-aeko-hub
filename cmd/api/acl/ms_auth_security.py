"""Resolve ms-auth Bearer tokens through GET /api/profile."""

from typing import NamedTuple

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
