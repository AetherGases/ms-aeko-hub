"""Shared doubles for ms-auth Bearer authentication in route tests."""

from cmd.api.acl.ms_auth_security import MsAuthPrincipal
from internal.http.ms_auth_dependencies import require_ms_auth_principal
from tests.test_profile_api import PROFILE_PAYLOAD


def ms_auth_principal(
    *,
    access_token: str = "ms-access",
    id_external_user: int = 12345,
    id_external_company: int = 90,
    profile: dict | None = None,
) -> MsAuthPrincipal:
    """Build a principal for dependency overrides."""
    payload = dict(profile or PROFILE_PAYLOAD)
    payload["id"] = id_external_user
    if "enterprise" in payload and isinstance(payload["enterprise"], dict):
        payload["enterprise"] = {**payload["enterprise"], "id": id_external_company}
    return MsAuthPrincipal(access_token, id_external_user, id_external_company, payload)


def override_ms_auth(app, principal: MsAuthPrincipal | None = None):
    """Override the ms-auth dependency on a FastAPI app."""

    bound = principal or ms_auth_principal()

    async def _dependency():
        yield bound

    app.dependency_overrides[require_ms_auth_principal] = _dependency
