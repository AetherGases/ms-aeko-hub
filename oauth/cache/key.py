"""Build Redis key names for OAuth authorization codes and hub-token sessions."""

import hashlib


def code_key(code: str) -> str:
    """Return the Redis key that stores an authorization code."""
    return f"oauth:code:{code}"


def session_key(access_token: str) -> str:
    """Return the Redis key that stores a hub access-token session."""
    digest = hashlib.sha256(access_token.encode("ascii")).hexdigest()
    return f"oauth:session:{digest}"
