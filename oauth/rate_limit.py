"""Count ChatGPT Sign-in attempts per email in Redis without resetting the window TTL."""

from oauth.cache.key import rate_limit_email_key
from oauth.constants import (
    OAUTH_AUTHORIZE_RATE_LIMIT_MAX,
    OAUTH_AUTHORIZE_RATE_LIMIT_WINDOW_SECONDS,
)


def record_attempt(redis_client, key: str, window_seconds: int) -> int:
    """Increment a window counter with SET NX on first hit and INCR after that."""
    created = redis_client.set(key, "1", nx=True, ex=window_seconds)
    if created:
        return 1
    return int(redis_client.incr(key))


def authorize_rate_limit_exceeded(redis_client, *, email: str) -> bool:
    """Record one Sign-in attempt and return whether this email is over the cap."""
    window = OAUTH_AUTHORIZE_RATE_LIMIT_WINDOW_SECONDS
    cap = OAUTH_AUTHORIZE_RATE_LIMIT_MAX
    email_count = record_attempt(redis_client, rate_limit_email_key(email), window)
    return email_count > cap
