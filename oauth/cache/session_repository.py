"""Persist and retrieve OAuth hub access-token sessions through Redis."""

import hashlib
import json
import os
from base64 import urlsafe_b64decode, urlsafe_b64encode

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from oauth.cache.key import session_key
from oauth.constants import OAUTH_SESSION_ENCRYPTION_KEY


def _aesgcm_key() -> bytes:
    raw = OAUTH_SESSION_ENCRYPTION_KEY.strip()
    if len(raw) == 64:
        try:
            return bytes.fromhex(raw)
        except ValueError:
            pass
    data = raw.encode("utf-8")
    if len(data) in {16, 24, 32}:
        return data
    return hashlib.sha256(data).digest()


def _encrypt_secret(plaintext: str) -> str:
    nonce = os.urandom(12)
    ciphertext = AESGCM(_aesgcm_key()).encrypt(nonce, plaintext.encode("utf-8"), None)
    return urlsafe_b64encode(nonce + ciphertext).decode("ascii")


def _decrypt_secret(payload: str) -> str:
    packed = urlsafe_b64decode(payload.encode("ascii") + b"=" * (-len(payload) % 4))
    if len(packed) <= 12:
        raise ValueError("Invalid session secret.")
    nonce, ciphertext = packed[:12], packed[12:]
    plaintext = AESGCM(_aesgcm_key()).decrypt(nonce, ciphertext, None)
    return plaintext.decode("utf-8")


class Repository:
    def __init__(self, redis_client):
        self.redis = redis_client

    def save(self, access_token, document, ttl) -> None:
        """Persist a hub-token session document with the supplied TTL."""
        stored = dict(document)
        token = stored.get("ms_auth_access_token")
        if isinstance(token, str) and token:
            stored["ms_auth_access_token"] = _encrypt_secret(token)
        self.redis.set(session_key(access_token), json.dumps(stored), ex=ttl)

    def get(self, access_token):
        """Return the stored hub-token session document, if present."""
        payload = self.redis.get(session_key(access_token))
        if payload is None:
            return None

        decoded = payload.decode() if isinstance(payload, bytes) else payload
        document = json.loads(decoded)
        token = document.get("ms_auth_access_token")
        if not isinstance(token, str) or not token:
            return document
        try:
            document["ms_auth_access_token"] = _decrypt_secret(token)
        except Exception:
            return None
        return document

    def delete(self, access_token) -> None:
        """Remove the hub-token session bound to the access token, if present."""
        self.redis.delete(session_key(access_token))
