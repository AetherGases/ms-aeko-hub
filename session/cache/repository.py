"""Persist and retrieve session windows through Redis."""

import json
import os
from datetime import datetime

from internal.shared import Module, logged
from session.cache.cache import ICacheRepository
from session.cache.key import (
    activity_key,
    session_id_from_window_key,
    window_key,
    window_scan_pattern,
)
from session.entity import Message, SessionWindow


def _window_ttl_seconds() -> int:
    inactivity_seconds = int(os.environ["SESSION_INACTIVITY_MINUTES"]) * 60
    return inactivity_seconds + inactivity_seconds


class Repository(ICacheRepository):
    def __init__(self, redis_client, scan_count=100):
        self.redis = redis_client
        self.scan_count = scan_count

    @logged(Module.DATABASE, "session_cache.list_expired_windows")
    def list_expired_windows(self) -> list[str]:
        """Return session identifiers whose activity key expired while a window remains."""
        expired = []
        for key in self.redis.scan_iter(match=window_scan_pattern(), count=self.scan_count):
            decoded = key.decode() if isinstance(key, bytes) else key
            id_session = session_id_from_window_key(decoded)
            if not self.redis.exists(activity_key(id_session)):
                expired.append(id_session)
        return expired

    @logged(Module.DATABASE, "session_cache.get_window")
    def get_window(self, id_session: str) -> SessionWindow | None:
        """Retrieve the stored conversation window for a session."""
        payload = self.redis.get(window_key(id_session))
        if payload is None:
            return None

        decoded = payload.decode() if isinstance(payload, bytes) else payload
        document = json.loads(decoded)
        return SessionWindow(
            id_user=document["id_user"],
            messages=[
                Message(
                    input=message["input"],
                    output=message["output"],
                    submitted_at=datetime.fromisoformat(message["submitted_at"]),
                )
                for message in document["messages"]
            ],
        )

    @logged(Module.DATABASE, "session_cache.set_window")
    def set_window(self, id_session: str, id_user: str, messages: list[Message]) -> None:
        """Persist the current conversation window for a session with a TTL of at least inactivity seconds."""
        document = {
            "id_user": id_user,
            "messages": [
                {
                    "input": message.input,
                    "output": message.output,
                    "submitted_at": message.submitted_at.isoformat(),
                }
                for message in messages
            ],
        }
        self.redis.set(window_key(id_session), json.dumps(document), ex=_window_ttl_seconds())

    @logged(Module.DATABASE, "session_cache.set_activity")
    def set_activity(self, id_session: str, ttl_seconds: int) -> None:
        """Refresh the inactivity marker for a session."""
        self.redis.set(activity_key(id_session), "", ex=ttl_seconds)

    @logged(Module.DATABASE, "session_cache.delete_window")
    def delete_window(self, id_session: str) -> None:
        """Remove the stored conversation window for a session."""
        self.redis.delete(window_key(id_session))
