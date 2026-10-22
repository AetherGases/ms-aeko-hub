"""Encode and decode this API's HS256 access tokens and PKCE S256 challenges."""

import base64
import hashlib
import hmac
import json
import time
from typing import NamedTuple

from oauth.constants import (
    OAUTH_ACCESS_TOKEN_TTL_SECONDS,
    OAUTH_AUDIENCE,
    OAUTH_ISSUER,
    OAUTH_SIGNING_KEY,
)


class AccessTokenClaims(NamedTuple):
    """Validated identity carried by a ChatGPT MCP access token."""

    id_external_user: int
    id_external_company: int


def b64url(data: bytes) -> str:
    """Encode bytes as unpadded base64url text."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    """Decode URL-safe Base64 without requiring padding."""
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def pkce_s256(verifier: str) -> str:
    """Return the S256 code challenge for a PKCE verifier."""
    return b64url(hashlib.sha256(verifier.encode("ascii")).digest())


def encode_access_token(
    id_external_user: int,
    id_external_company: int,
    ttl_seconds: int | None = None,
) -> str:
    """Return a signed access token for one user and company."""
    ttl = (
        ttl_seconds
        if isinstance(ttl_seconds, int) and ttl_seconds > 0
        else OAUTH_ACCESS_TOKEN_TTL_SECONDS
    )
    now = int(time.time())
    header = b64url(
        json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode()
    )
    payload = b64url(
        json.dumps(
            {
                "iss": OAUTH_ISSUER,
                "aud": OAUTH_AUDIENCE,
                "sub": str(id_external_user),
                "id_external_company": id_external_company,
                "iat": now,
                "exp": now + ttl,
                "scope": "mcp",
            },
            separators=(",", ":"),
        ).encode()
    )
    signing_input = f"{header}.{payload}".encode()
    signature = hmac.new(
        OAUTH_SIGNING_KEY.encode(), signing_input, hashlib.sha256
    ).digest()
    return f"{header}.{payload}.{b64url(signature)}"


def _positive_claim(value, field_name: str) -> int:
    """Read a positive integer claim from a JWT payload."""
    if isinstance(value, bool) or value is None:
        raise ValueError("Invalid access token.")
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str):
        stripped = value.strip()
        if stripped == "" or not stripped.isdigit():
            raise ValueError("Invalid access token.")
        parsed = int(stripped)
    else:
        raise ValueError("Invalid access token.")
    if parsed <= 0:
        raise ValueError("Invalid access token.")
    return parsed


def decode_access_token(token: str) -> AccessTokenClaims:
    """Return user and company claims from a valid access token, or raise ValueError."""
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("Invalid access token.")
    header_b64, payload_b64, signature_b64 = parts
    try:
        actual = _b64url_decode(signature_b64)
        payload = json.loads(_b64url_decode(payload_b64))
    except (ValueError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid access token.") from exc
    expected = hmac.new(
        OAUTH_SIGNING_KEY.encode(),
        f"{header_b64}.{payload_b64}".encode(),
        hashlib.sha256,
    ).digest()
    if not hmac.compare_digest(expected, actual):
        raise ValueError("Invalid access token.")
    if payload.get("iss") != OAUTH_ISSUER:
        raise ValueError("Invalid access token.")
    if payload.get("aud") != OAUTH_AUDIENCE:
        raise ValueError("Invalid access token.")
    if payload.get("scope") != "mcp":
        raise ValueError("Invalid access token.")
    exp = payload.get("exp")
    if not isinstance(exp, int) or int(time.time()) >= exp:
        raise ValueError("Invalid access token.")
    return AccessTokenClaims(
        id_external_user=_positive_claim(payload.get("sub"), "sub"),
        id_external_company=_positive_claim(
            payload.get("id_external_company"),
            "id_external_company",
        ),
    )
