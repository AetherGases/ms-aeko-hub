"""Define conversation service and persistence contracts and guardrail errors."""

from abc import ABC, abstractmethod
from datetime import datetime

from session.entity import Message, SendMessageResult, Session


class GuardrailRejectedError(Exception):
    """Raised when no conversation response is approved by the SDK reviewers."""


class IRepository(ABC):
    @abstractmethod
    def get_user_sessions(self, id_user: str) -> list[Session]:
        """Retrieve the sessions belonging to a user."""
        pass

    @abstractmethod
    def get_session(self, id_session: str) -> Session:
        """Retrieve a session by its internal identifier."""
        pass

    @abstractmethod
    def get_session_messages(self, id_session: str) -> list[Message]:
        """Retrieve the stored messages for a session."""
        pass

    @abstractmethod
    def get_session_messages_count(self, id_session: str) -> int:
        """Return the number of messages stored in a session."""
        pass

    @abstractmethod
    def create_session(self, id_user: str, user_repository) -> str:
        """Create an empty session for an existing user and return its identifier."""
        pass

    @abstractmethod
    def save_message(self, id_session: str, message: Message) -> None:
        """Append a message to the session and update its modification timestamp."""
        pass

    @abstractmethod
    def update_name(self, id_session: str, name: str) -> None:
        """Update the session name and modification timestamp."""
        pass

    @abstractmethod
    def get_sessions_updated_since(self, since: datetime) -> list[Session]:
        """Retrieve sessions whose modification time is at or after the supplied instant."""
        pass


class IService(ABC):
    @abstractmethod
    def get_user_sessions(self, id_external_user) -> list[Session]:
        """Retrieve the sessions belonging to a user."""
        pass

    @abstractmethod
    def get_session_messages(self, id_session: str) -> list[Message]:
        """Retrieve the stored messages for a session."""
        pass

    @abstractmethod
    def send_message(
        self,
        id_session: str,
        input: str,
        id_user: str,
        aeko_messenger_factory,
        aeko_session_factory,
        user_repository,
    ) -> SendMessageResult:
        """Send a conversation turn and persist the approved response with its run metrics."""
        pass

    @abstractmethod
    def _validate_session_and_user_allowance(
        self, id_session: str, id_user: str
    ) -> bool:
        """Reject oversized sessions and users who do not own them."""
        pass
