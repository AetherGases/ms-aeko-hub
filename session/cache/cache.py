"""Define the cache repository contract for session windows."""

from abc import ABC, abstractmethod

from session.entity import Message, SessionWindow


class ICacheRepository(ABC):
    @abstractmethod
    def list_expired_windows(self) -> list[str]:
        """Return session identifiers whose activity key expired while a window remains."""
        pass

    @abstractmethod
    def get_window(self, id_session: str) -> SessionWindow | None:
        """Retrieve the stored conversation window for a session."""
        pass

    @abstractmethod
    def set_window(
        self, id_session: str, id_user: str, messages: list[Message]
    ) -> None:
        """Persist the current conversation window for a session."""
        pass

    @abstractmethod
    def set_activity(self, id_session: str, ttl_seconds: int) -> None:
        """Refresh the inactivity marker for a session."""
        pass

    @abstractmethod
    def delete_window(self, id_session: str) -> None:
        """Remove the stored conversation window for a session."""
        pass
