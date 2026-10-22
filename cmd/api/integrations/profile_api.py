"""Frozen HTTP client for the ms-auth profile endpoint (GET /api/profile)."""

from typing import Any

from cmd.api.integrations.constants import PROFILE_MS_PATH, _TOOL_PROFILE_KEYS
from cmd.api.integrations.ms_auth_http import base_url, request_json


class ProfileError(RuntimeError):
    """Raised when a call to the auth microservice profile route cannot be completed."""


def get_profile(access_token: str) -> dict:
    """Fetch the logged-in user's profile from ms-auth and return the payload as-is."""
    url = f"{base_url()}{PROFILE_MS_PATH}"
    return request_json(
        "GET",
        url,
        error_type=ProfileError,
        headers={"Authorization": f"Bearer {access_token}"},
        json={},
    )


def profile_tool_catalog(
    ms_payload: dict, *, role: str, usecase: str
) -> dict[str, Any]:
    """Merge the ms-auth profile with Mongo role and usecase, omitting CPF, phone, and permissions."""

    catalog = {key: ms_payload[key] for key in _TOOL_PROFILE_KEYS if key in ms_payload}
    catalog["role"] = role
    catalog["usecase"] = usecase
    return catalog


def profile_id(payload: dict) -> int:
    """Return the profile id as a positive integer for use as id_external_user."""
    return _positive_int(payload.get("id"), "id")


def profile_enterprise_id(payload: dict) -> int:
    """Return the enterprise id from a GetMyProfileOutput-shaped payload."""
    enterprise = payload.get("enterprise")
    if not isinstance(enterprise, dict):
        raise ValueError("enterprise is required.")
    return _positive_int(enterprise.get("id"), "enterprise.id")


def sign_in_profile_sync(ms_auth_profile: dict) -> dict[str, Any]:
    """Extract the company id persisted after OAuth Sign in."""

    return {"id_external_company": profile_enterprise_id(ms_auth_profile)}


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
