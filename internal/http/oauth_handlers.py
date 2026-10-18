"""Expose OAuth 2.1 discovery, ChatGPT Sign in, and token endpoints."""

from html import escape
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from oauth.constants import AUTHORIZE_PATH, MCP_PROTECTED_RESOURCE_WELL_KNOWN_PATH, PROTECTED_RESOURCE_WELL_KNOWN_PATH, TOKEN_PATH
from oauth.discovery import (
    authorization_server_metadata_document,
    protected_resource_metadata_document,
    public_url,
)
from oauth.oauth import IService
from oauth.service import validate_authorize_parameters

router = APIRouter()

_WIDGETS_DIR = (
    Path(__file__).resolve().parents[2] / "cmd" / "api" / "acl" / "open_ai" / "widgets"
)
_SIGN_IN_TEMPLATE_PATH = _WIDGETS_DIR / "oauth_sign_in.html"
_MASCOT_PATH = _WIDGETS_DIR / "ic_aeko_mascot.png"
MASCOT_PATH = "/ai/oauth/ic_aeko_mascot.png"


def _sign_in_template() -> str:
    """Load the OAuth sign-in HTML template."""
    return _SIGN_IN_TEMPLATE_PATH.read_text(encoding="utf-8")


def get_oauth_service(request: Request) -> IService:
    """Return the bound OAuth service, or raise HTTP 503."""
    service = getattr(request.app.state, "oauth", None)
    if service is None:
        raise HTTPException(status_code=503, detail="OAuth is not initialized")
    return service


def _hidden(name: str, value: str) -> str:
    return f'<input type="hidden" name="{escape(name)}" value="{escape(value)}">'


def render_sign_in(
    *,
    client_id: str,
    redirect_uri: str,
    state: str,
    code_challenge: str,
    code_challenge_method: str,
    resource: str | None = None,
    error: str | None = None,
    email: str = "",
) -> str:
    """Return the ChatGPT Sign in webview HTML for the supplied OAuth parameters."""
    hidden = [
        _hidden("client_id", client_id),
        _hidden("redirect_uri", redirect_uri),
        _hidden("state", state),
        _hidden("code_challenge", code_challenge),
        _hidden("code_challenge_method", code_challenge_method),
    ]
    if resource:
        hidden.append(_hidden("resource", resource))
    if error:
        error_block = (
            '<div style="'
            "padding: 12px 14px;"
            "border-radius: 14px;"
            "background: rgba(255, 230, 230, 0.9);"
            "border: 1px solid rgba(200, 80, 80, 0.25);"
            "color: #8b3a3a;"
            "font-size: 13px;"
            "font-weight: 600;"
            '">'
            f"{escape(error)}"
            "</div>"
        )
    else:
        error_block = ""
    return (
        _sign_in_template()
        .replace("__FORM_ACTION__", public_url(AUTHORIZE_PATH))
        .replace("__HIDDEN_FIELDS__", "".join(hidden))
        .replace("__ERROR_BLOCK__", error_block)
        .replace("__EMAIL_VALUE__", escape(email))
    )


@router.get(MASCOT_PATH, include_in_schema=False)
def oauth_sign_in_mascot():
    """Serve the mascot image used by the OAuth sign-in page."""
    return FileResponse(_MASCOT_PATH, media_type="image/png")


@router.get("/.well-known/oauth-authorization-server", include_in_schema=False)
def authorization_server_metadata():
    """Return OAuth 2.1 authorization-server metadata for ChatGPT discovery."""
    return authorization_server_metadata_document()


@router.get(PROTECTED_RESOURCE_WELL_KNOWN_PATH, include_in_schema=False)
def protected_resource_metadata():
    """Return OAuth protected-resource metadata for the MCP resource."""
    return protected_resource_metadata_document()


@router.get(MCP_PROTECTED_RESOURCE_WELL_KNOWN_PATH, include_in_schema=False)
def mcp_protected_resource_metadata():
    """Return protected-resource metadata at the MCP resource path (RFC 9728)."""
    return protected_resource_metadata_document()


@router.get(AUTHORIZE_PATH, tags=["OAuth"])
def authorize_get(
    client_id: str,
    redirect_uri: str,
    state: str,
    code_challenge: str,
    code_challenge_method: str,
    response_type: str = "code",
    resource: str | None = None,
):
    """Render the ChatGPT Sign in webview after validating the authorize query."""
    if response_type != "code":
        raise HTTPException(status_code=400, detail="response_type must be code.")
    try:
        validate_authorize_parameters(
            client_id=client_id,
            redirect_uri=redirect_uri,
            code_challenge_method=code_challenge_method,
            resource=resource,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return HTMLResponse(
        render_sign_in(
            client_id=client_id,
            redirect_uri=redirect_uri,
            state=state,
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
            resource=resource,
        )
    )


@router.post(AUTHORIZE_PATH, tags=["OAuth"])
def authorize_post(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    client_id: str = Form(...),
    redirect_uri: str = Form(...),
    state: str = Form(...),
    code_challenge: str = Form(...),
    code_challenge_method: str = Form(...),
    resource: str | None = Form(None),
):
    """Authenticate through the OAuth service and redirect to the client, or stay on Sign in."""
    sign_in_kwargs = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": code_challenge_method,
        "resource": resource,
        "email": email,
    }
    try:
        location = get_oauth_service(request).authorize(
            email,
            password,
            client_id=client_id,
            redirect_uri=redirect_uri,
            state=state,
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
            resource=resource,
        )
    except ValueError:
        return HTMLResponse(
            render_sign_in(
                **sign_in_kwargs,
                error="Sign in failed.",
            ),
            status_code=401,
        )
    return RedirectResponse(url=location, status_code=302)


@router.post(TOKEN_PATH, tags=["OAuth"])
def token_post(
    request: Request,
    grant_type: str = Form(...),
    code: str = Form(...),
    client_id: str = Form(...),
    redirect_uri: str = Form(...),
    code_verifier: str = Form(...),
    resource: str | None = Form(None),
):
    """Exchange an authorization code for this API's Bearer access token."""
    if grant_type != "authorization_code":
        raise HTTPException(status_code=400, detail="grant_type must be authorization_code.")
    try:
        return get_oauth_service(request).exchange(
            code,
            client_id=client_id,
            redirect_uri=redirect_uri,
            code_verifier=code_verifier,
            resource=resource,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
