"""Encrypt ms-auth access tokens stored in Redis OAuth documents."""

import hashlib
import os
from base64 import urlsafe_b64decode, urlsafe_b64encode

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from oauth.constants import OAUTH_SESSION_ENCRYPTION_KEY


def _aesgcm_key() -> bytes:
    """Derive the AES-GCM key from the configured encryption secret."""
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


def encrypt_secret(plaintext: str) -> str:
    """Return AES-GCM ciphertext for a secret, as url-safe Base64."""
    nonce = os.urandom(12)
    ciphertext = AESGCM(_aesgcm_key()).encrypt(nonce, plaintext.encode("utf-8"), None)
    return urlsafe_b64encode(nonce + ciphertext).decode("ascii")


def decrypt_secret(payload: str) -> str:
    """Return the plaintext secret packed by encrypt_secret."""
    packed = urlsafe_b64decode(payload.encode("ascii") + b"=" * (-len(payload) % 4))
    if len(packed) <= 12:
        raise ValueError("Invalid session secret.")
    nonce, ciphertext = packed[:12], packed[12:]
    plaintext = AESGCM(_aesgcm_key()).decrypt(nonce, ciphertext, None)
    return plaintext.decode("utf-8")


def seal_ms_auth_access_token(document: dict) -> dict:
    """Return a copy whose ms_auth_access_token is encrypted, if present."""
    stored = dict(document)
    token = stored.get("ms_auth_access_token")
    if isinstance(token, str) and token:
        stored["ms_auth_access_token"] = encrypt_secret(token)
    return stored


def open_ms_auth_access_token(document: dict) -> dict | None:
    """Decrypt ms_auth_access_token in place. Return None if decryption fails."""
    token = document.get("ms_auth_access_token")
    if not isinstance(token, str) or not token:
        return document
    try:
        document["ms_auth_access_token"] = decrypt_secret(token)
    except Exception:
        return None
    return document
