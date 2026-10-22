"""Persist and retrieve conversations and messages through MongoDB."""

from datetime import datetime

from internal.shared import Module, logged
from session.database import query as q
from session.entity import Message, Session
from session.session import IRepository

from user.user import IRepository as IUserRepository


class Repository(IRepository):
    def __init__(self, db):
        """Bind the MongoDB database handle."""
        self.db = db

    @logged(Module.DATABASE, "session.get_user_sessions")
    def get_user_sessions(self, id_user: str) -> list[Session]:
        """Retrieve the sessions belonging to a user."""
        try:
            query, projection = q.get_user_sessions_query(id_user)
            sessions_data = self.db["session"].find(query, projection)
            sessions = [session_from_data(data) for data in sessions_data]
            if not sessions:
                raise ValueError(f"No sessions found for user with id_user {id_user}.")
            return sessions
        except ValueError as e:
            raise e
        except Exception as e:
            raise RuntimeError(f"Error fetching user sessions from database: {e}")

    @logged(Module.DATABASE, "session.get_session")
    def get_session(self, id_session: str) -> Session:
        """Retrieve a session by its internal identifier."""
        try:
            query, projection = q.get_session_query(id_session)
            session_data = self.db["session"].find_one(query, projection)
            if not session_data:
                raise ValueError(f"No session found with id_session {id_session}.")
            return session_from_data(session_data)
        except ValueError as e:
            raise e
        except Exception as e:
            raise RuntimeError(f"Error fetching session from database: {e}")

    @logged(Module.DATABASE, "session.get_session_messages")
    def get_session_messages(self, id_session: str) -> list[Message]:
        """Retrieve the stored messages for a session."""
        try:
            query, projection = q.get_session_messages_query(id_session)
            session_data = self.db["session"].find_one(query, projection)
            if session_data is None:
                raise ValueError(f"No session found with id_session {id_session}.")
            return [
                message_from_data(data) for data in session_data.get("messages", [])
            ]
        except ValueError as e:
            raise e
        except Exception as e:
            raise RuntimeError(f"Error fetching session messages from database: {e}")

    @logged(Module.DATABASE, "session.get_session_messages_count")
    def get_session_messages_count(self, id_session: str) -> int:
        """Return the number of messages stored in a session."""
        try:
            query, projection = q.get_session_messages_count_query(id_session)
            session_data = self.db["session"].find_one(query, projection)
            if not session_data:
                raise ValueError(f"No session found with id_session {id_session}.")
            return session_data.get("messages_count")
        except ValueError as e:
            raise e
        except Exception as e:
            raise RuntimeError(f"Error fetching session messages from database: {e}")

    @logged(Module.DATABASE, "session.create_session")
    def create_session(self, id_user: str, user_repository: IUserRepository) -> str:
        """Create an empty session for an existing user and return its identifier."""
        try:
            if not user_repository.get_user_by_id(id_user):
                raise ValueError(f"User with id_user {id_user} does not exist.")

            query = q.get_create_session_query(id_user)
            result = self.db["session"].insert_one(query)
            return str(result.inserted_id)
        except ValueError as e:
            raise e
        except Exception as e:
            raise RuntimeError(f"Error creating session in database: {e}")

    @logged(Module.DATABASE, "session.save_message")
    def save_message(self, id_session: str, message: Message) -> None:
        """Append a message to the session and update its modification timestamp."""
        try:
            query = q.get_save_message_query(
                input=message.input,
                output=message.output,
                submitted_at=message.submitted_at,
            )
            self.db["session"].update_one(q.get_session_filter(id_session), query)
        except Exception as e:
            raise RuntimeError(f"Error saving message to database: {e}")

    @logged(Module.DATABASE, "session.update_name")
    def update_name(self, id_session: str, name: str) -> None:
        """Update the session name and modification timestamp."""
        try:
            self.db["session"].update_one(
                q.get_session_filter(id_session), q.get_update_name_query(name)
            )
        except Exception as e:
            raise RuntimeError(f"Error updating session name in database: {e}")

    @logged(Module.DATABASE, "session.get_sessions_updated_since")
    def get_sessions_updated_since(self, since) -> list[Session]:
        """Retrieve sessions whose modification time is at or after the supplied instant."""
        try:
            query, projection = q.get_sessions_updated_since_query(since)
            sessions_data = self.db["session"].find(query, projection)
            return [session_from_data(data) for data in sessions_data]
        except Exception as e:
            raise RuntimeError(
                f"Error fetching recently updated sessions from database: {e}"
            )


def message_from_data(data: dict) -> Message:
    """Map a stored message document to a domain message."""
    submitted_at = data["submitted_at"]
    if isinstance(submitted_at, str):
        submitted_at = datetime.fromisoformat(submitted_at.replace("Z", "+00:00"))
    return Message(
        input=data["input"],
        output=data["output"],
        submitted_at=submitted_at,
    )


def session_from_data(data: dict) -> Session:
    """Map a stored session document to a domain session."""
    return Session(
        id=str(data["_id"]),
        id_user=str(data["id_user"]),
        name=data["name"],
        messages=[message_from_data(message) for message in data.get("messages", [])],
        created_at=data.get("created_at"),
        updated_at=data.get("updated_at"),
    )
