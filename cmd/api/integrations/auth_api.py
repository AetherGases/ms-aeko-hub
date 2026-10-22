"""Frozen HTTP client for the auth microservice login endpoint."""

from cmd.api.integrations.constants import AUTH_MS_LOGIN_PATH
from cmd.api.integrations.ms_auth_http import base_url, request_json


class AuthError(RuntimeError):
    """Raised when a call to the auth microservice cannot be completed."""


def login(email: str, password: str) -> dict:
    """Authenticate with email and password and return the microservice payload as-is."""
    url = f"{base_url()}{AUTH_MS_LOGIN_PATH}"
    return request_json(
        "POST",
        url,
        error_type=AuthError,
        json={"email": email, "password": password},
    )
