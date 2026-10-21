"""OAuth authorization-server configuration."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)

OAUTH_SIGNING_KEY = os.environ["OAUTH_SIGNING_KEY"]
OAUTH_ISSUER = os.environ["OAUTH_ISSUER"]
OAUTH_AUDIENCE = os.environ["OAUTH_AUDIENCE"]
OAUTH_CLIENT_ID = os.environ["OAUTH_CLIENT_ID"]
OAUTH_AUTHORIZATION_CODE_TTL_SECONDS = int(os.environ["OAUTH_AUTHORIZATION_CODE_TTL_SECONDS"])
OAUTH_ACCESS_TOKEN_TTL_SECONDS = int(os.environ["OAUTH_ACCESS_TOKEN_TTL_SECONDS"])
OAUTH_SESSION_ENCRYPTION_KEY = os.environ["OAUTH_SESSION_ENCRYPTION_KEY"]
OAUTH_AUTHORIZE_RATE_LIMIT_MAX = int(os.environ.get("OAUTH_AUTHORIZE_RATE_LIMIT_MAX", "5"))
OAUTH_AUTHORIZE_RATE_LIMIT_WINDOW_SECONDS = int(
    os.environ.get("OAUTH_AUTHORIZE_RATE_LIMIT_WINDOW_SECONDS", "900")
)

AUTHORIZE_PATH = "/ai/oauth/authorize"
TOKEN_PATH = "/ai/oauth/token"
REVOKE_PATH = "/ai/oauth/revoke"
PROTECTED_RESOURCE_WELL_KNOWN_PATH = "/.well-known/oauth-protected-resource"
MCP_PROTECTED_RESOURCE_WELL_KNOWN_PATH = (
    "/ai/mcp/.well-known/oauth-protected-resource"
)