"""Define the domain entities for conversations and messages."""

from datetime import datetime, timedelta


class Message:
    """One exchanged turn: what was asked, what was answered, and when."""

    input: str
    output: str
    submitted_at: datetime

    def __init__(self, input: str, output: str, submitted_at: datetime):
        self.input = input
        self.output = output
        self.submitted_at = submitted_at


class Session:
    id: str
    id_user: str
    name: str
    messages: list[Message]
    created_at: datetime | None
    updated_at: datetime | None

    def __init__(self, id: str, id_user: str, name: str, messages: list[Message], created_at: datetime | None = None, updated_at: datetime | None = None):
        self.id = id
        self.id_user = id_user
        self.name = name
        self.messages = messages
        self.created_at = created_at
        self.updated_at = updated_at


class SendMessageResult:
    """The persisted turn together with the session it belongs to."""

    message: Message
    session: Session

    def __init__(self, message: Message, session: Session):
        self.message = message
        self.session = session


class SessionWindow:
    """The trailing conversation turns that belong to one inactivity window."""

    id_user: str
    messages: list[Message]

    def __init__(self, id_user: str, messages: list[Message]):
        self.id_user = id_user
        self.messages = messages

    @staticmethod
    def derive(messages: list[Message], inactivity_minutes: int) -> list[Message]:
        """Return the final run of messages separated by less than the inactivity threshold."""
        if not messages:
            return []

        threshold = timedelta(minutes=inactivity_minutes)
        window = [messages[-1]]
        for index in range(len(messages) - 2, -1, -1):
            gap = messages[index + 1].submitted_at - messages[index].submitted_at
            if gap >= threshold:
                break
            window.insert(0, messages[index])
        return window
        