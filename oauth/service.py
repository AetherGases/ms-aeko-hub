"""Orchestrate ChatGPT Sign in against ms-auth and return the ms-auth access token on exchange."""

import hmac
import re
import secrets
from urllib.parse import quote, urlparse

from cmd.api.integrations.auth_api import login
from cmd.api.integrations.profile_api import get_profile, profile_enterprise_id, profile_id
from oauth.constants import (
    OAUTH_AUDIENCE,
    OAUTH_AUTHORIZATION_CODE_TTL_SECONDS,
    OAUTH_ACCESS_TOKEN_TTL_SECONDS,
    OAUTH_CLIENT_ID,
    OAUTH_ISSUER,
)
from oauth.oauth import IService
from oauth.token import pkce_s256

_callback_id = r"[A-Za-z0-9_-]+"
_cimd_callback = re.compile(rf"^https://chatgpt\.com/oauth/{_callback_id}/client\.json$")
_redirect_connector = re.compile(rf"^https://chatgpt\.com/connector/oauth/{_callback_id}$")
_chatgpt_redirect = "https://chatgpt.com/connector_platform_oauth_redirect"
_cimd_client = "https://chatgpt.com/oauth/client.json"


def _expires_in_from_login_payload(payload: dict) -> int:
    """Read ms-auth token lifetime from the login payload when present."""
    for key in ("expiresIn", "expires_in", "accessTokenExpiresIn"):
        value = payload.get(key)
        if isinstance(value, int) and value > 0:
            return value
    return OAUTH_ACCESS_TOKEN_TTL_SECONDS


def accepted_client_id(client_id: str) -> bool:
    """Return whether the client_id is this API's client or a ChatGPT CIMD URL."""
    return (
        client_id == OAUTH_CLIENT_ID
        or client_id == _cimd_client
        or _cimd_callback.fullmatch(client_id) is not None
    )


def accepted_redirect_uri(redirect_uri: str) -> bool:
    """Return whether the redirect_uri is an accepted ChatGPT or localhost Inspector URI."""
    if redirect_uri == _chatgpt_redirect:
        return True
    if _redirect_connector.fullmatch(redirect_uri) is not None:
        return True
    parsed = urlparse(redirect_uri)
    return parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}


def validate_authorize_parameters(
    *,
    client_id: str,
    redirect_uri: str,
    code_challenge_method: str,
    resource=None,
) -> None:
    """Reject PKCE methods other than S256 and unaccepted clients, redirects, or resources."""
    if code_challenge_method != "S256":
        raise ValueError("code_challenge_method must be S256.")
    if not accepted_client_id(client_id):
        raise ValueError("client_id is not accepted.")
    if not accepted_redirect_uri(redirect_uri):
        raise ValueError("redirect_uri is not accepted.")
    if resource is not None and resource != "" and resource != OAUTH_AUDIENCE:
        raise ValueError("resource is not accepted.")


class Service(IService):
    def __init__(self, repository, users=None):
        self.repository = repository
        self.users = users

    def authorize(
        self,
        email: str,
        password: str,
        *,
        client_id: str,
        redirect_uri: str,
        state: str,
        code_challenge: str,
        code_challenge_method: str,
        resource=None,
    ) -> str:
        """Authenticate the user and return the client redirect URL with code, state, and iss."""
        validate_authorize_parameters(
            client_id=client_id,
            redirect_uri=redirect_uri,
            code_challenge_method=code_challenge_method,
            resource=resource,
        )
        try:
            payload = login(email, password)
        except Exception as exc:
            raise ValueError("Sign in failed.") from exc
        if payload.get("authenticated") is not True:
            raise ValueError("Sign in failed.")
        access_token = payload.get("accessToken")
        if not access_token:
            raise ValueError("Sign in failed.")
        try:
            profile = get_profile(access_token)
            id_external_user = profile_id(profile)
            id_external_company = profile_enterprise_id(profile)
        except Exception as exc:
            raise ValueError("Sign in failed.") from exc
        if self.users is not None:
            try:
                self.users.apply_sign_in_profile(
                    id_external_user,
                    ms_auth_profile=profile,
                )
            except Exception as exc:
                raise ValueError("Sign in failed.") from exc
        code = secrets.token_urlsafe(32)
        self.repository.save(
            code,
            {
                "id_external_user": id_external_user,
                "id_external_company": id_external_company,
                "ms_auth_access_token": access_token,
                "ms_auth_access_token_expires_in": _expires_in_from_login_payload(payload),
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "code_challenge": code_challenge,
                "code_challenge_method": code_challenge_method,
            },
            OAUTH_AUTHORIZATION_CODE_TTL_SECONDS,
        )
        query = (
            f"code={quote(code, safe='')}&state={quote(state, safe='')}&iss={quote(OAUTH_ISSUER, safe=':/')}"
        )
        return f"{redirect_uri}?{query}"

    def exchange(
        self,
        code: str,
        *,
        client_id: str,
        redirect_uri: str,
        code_verifier: str,
        resource=None,
    ) -> dict:
        """Exchange a one-time authorization code for the ms-auth access token."""
        if resource is not None and resource != "" and resource != OAUTH_AUDIENCE:
            raise ValueError("resource is not accepted.")
        document = self.repository.pop(code)
        if document is None:
            raise ValueError("Invalid authorization code.")
        if document.get("client_id") != client_id or document.get("redirect_uri") != redirect_uri:
            raise ValueError("Invalid authorization code.")
        try:
            challenge = pkce_s256(code_verifier)
        except (UnicodeEncodeError, ValueError) as exc:
            raise ValueError("Invalid PKCE verifier.") from exc
        stored = document.get("code_challenge") or ""
        if document.get("code_challenge_method") != "S256" or not hmac.compare_digest(
            challenge, stored
        ):
            raise ValueError("Invalid PKCE verifier.")
        access_token = document.get("ms_auth_access_token")
        if not access_token:
            raise ValueError("Invalid authorization code.")
        expires_in = document.get("ms_auth_access_token_expires_in")
        if not isinstance(expires_in, int) or expires_in <= 0:
            expires_in = OAUTH_ACCESS_TOKEN_TTL_SECONDS
        return {
            "access_token": access_token,
            "token_type": "Bearer",
            "expires_in": expires_in,
        }
