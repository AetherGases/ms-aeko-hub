"""Persist and retrieve OAuth hub access-token sessions through Redis."""

import json

from oauth.cache.key import session_key


class Repository:
    def __init__(self, redis_client):
        self.redis = redis_client

    def save(self, access_token, document, ttl) -> None:
        """Persist a hub-token session document with the supplied TTL."""
        self.redis.set(session_key(access_token), json.dumps(document), ex=ttl)

    def get(self, access_token):
        """Return the stored hub-token session document, if present."""
        payload = self.redis.get(session_key(access_token))
        if payload is None:
            return None

        decoded = payload.decode() if isinstance(payload, bytes) else payload
        return json.loads(decoded)
