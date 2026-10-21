"""Persist and retrieve OAuth hub access-token sessions through Redis."""

import json

from oauth.cache.key import session_key
from oauth.cache.secret import open_ms_auth_access_token, seal_ms_auth_access_token


class Repository:
    def __init__(self, redis_client):
        self.redis = redis_client

    def save(self, access_token, document, ttl) -> None:
        """Persist a hub-token session document with the supplied TTL."""
        stored = seal_ms_auth_access_token(document)
        self.redis.set(session_key(access_token), json.dumps(stored), ex=ttl)

    def get(self, access_token):
        """Return the stored hub-token session document, if present."""
        payload = self.redis.get(session_key(access_token))
        if payload is None:
            return None

        decoded = payload.decode() if isinstance(payload, bytes) else payload
        document = json.loads(decoded)
        return open_ms_auth_access_token(document)

    def delete(self, access_token) -> None:
        """Remove the hub-token session bound to the access token, if present."""
        self.redis.delete(session_key(access_token))
