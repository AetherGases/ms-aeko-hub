"""Build Redis key names for OAuth authorization codes, sessions, and Sign-in rate limits."""

import hashlib


def code_key(code: str) -> str:
    """Return the Redis key that stores an authorization code."""
    digest = hashlib.sha256(code.encode("ascii")).hexdigest()
    return f"oauth:code:{digest}"


def rate_limit_email_key(email: str) -> str:
    """Return the Redis key that counts Sign-in attempts for one email."""
    return f"oauth:ratelimit:email:{email.strip().lower()}"


def session_key(access_token: str) -> str:
    """Return the Redis key that stores a hub access-token session."""
    digest = hashlib.sha256(access_token.encode("ascii")).hexdigest()
    return f"oauth:session:{digest}"
