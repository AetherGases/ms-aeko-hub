"""Build Redis key names for session activity and window caches."""

from session.constants import SESSION_KEY_PREFIX


def activity_key(id_session: str) -> str:
    """Return the Redis key that tracks inactivity for a session."""
    return f"{SESSION_KEY_PREFIX}:{id_session}:activity"


def window_key(id_session: str) -> str:
    """Return the Redis key that stores the current conversation window."""
    return f"{SESSION_KEY_PREFIX}:{id_session}:window"


def window_scan_pattern() -> str:
    """Return the pattern used to scan stored conversation windows."""
    return f"{SESSION_KEY_PREFIX}:*:window"


def session_id_from_window_key(key: str) -> str:
    """Extract the session identifier encoded in a window key."""
    return key.split(":")[2]
