"""Persist and retrieve OAuth authorization codes through Redis."""

import json

from oauth.cache.key import code_key
from oauth.cache.secret import open_ms_auth_access_token, seal_ms_auth_access_token


class Repository:
    def __init__(self, redis_client):
        self.redis = redis_client

    def save(self, code, document, ttl) -> None:
        """Persist an authorization code document with the supplied TTL."""
        stored = seal_ms_auth_access_token(document)
        self.redis.set(code_key(code), json.dumps(stored), ex=ttl)

    def pop(self, code):
        """Remove and return the stored authorization code document, if present."""
        payload = self.redis.getdel(code_key(code))
        if payload is None:
            return None

        decoded = payload.decode() if isinstance(payload, bytes) else payload
        document = json.loads(decoded)
        return open_ms_auth_access_token(document)
