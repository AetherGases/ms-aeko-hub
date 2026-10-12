"""Verify ms-auth Bearer resolution through the profile endpoint."""

import pytest

from cmd.api.acl.ms_auth_security import (
    MsAuthPrincipal,
    parse_bearer_authorization,
    resolve_ms_auth_access_token,
)
from cmd.api.integrations.profile_api import ProfileError
from tests.test_profile_api import PROFILE_PAYLOAD


def test_parse_bearer_authorization_reads_the_token():
    """Verify that parse bearer authorization reads the token."""
    assert parse_bearer_authorization("Bearer ms-access") == "ms-access"
    assert parse_bearer_authorization("bearer ms-access") == "ms-access"
    assert parse_bearer_authorization(None) is None
    assert parse_bearer_authorization("Basic abc") is None


def test_resolve_ms_auth_access_token_returns_principal(monkeypatch):
    """Verify that resolve ms auth access token returns principal."""
    monkeypatch.setattr(
        "cmd.api.acl.ms_auth_security.get_profile",
        lambda token: PROFILE_PAYLOAD,
    )

    principal = resolve_ms_auth_access_token("ms-access")

    assert principal == MsAuthPrincipal("ms-access", 1, 90, PROFILE_PAYLOAD)


def test_resolve_ms_auth_access_token_rejects_profile_errors(monkeypatch):
    """Verify that resolve ms auth access token rejects profile errors."""

    def fail(_token):
        """Raise a profile error for invalid tokens."""
        raise ProfileError("denied")

    monkeypatch.setattr("cmd.api.acl.ms_auth_security.get_profile", fail)

    with pytest.raises(ValueError, match="Invalid or expired access token."):
        resolve_ms_auth_access_token("ms-access")
