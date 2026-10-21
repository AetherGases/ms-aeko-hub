"""Coordinate domain operations for agent-to-agent messaging."""

from typing import Any

from cmd.api.integrations.a2a.a2a import IService
from cmd.api.integrations.a2a.entity import A2AMessage
from user.user import IRepository as IUserRepository


def _positive_int(value: Any, field_name: str) -> int:
    """Accept a positive integer or numeric string and reject bools or other values."""

    if isinstance(value, bool) or value is None:
        raise ValueError(f"{field_name} must be a positive integer.")

    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str):
        stripped = value.strip()
        if stripped == "" or not stripped.isdigit():
            raise ValueError(f"{field_name} must be a positive integer.")
        parsed = int(stripped)
    else:
        raise ValueError(f"{field_name} must be a positive integer.")

    if parsed <= 0:
        raise ValueError(f"{field_name} must be a positive integer.")

    return parsed


def _effective_session_name(session_name: str | None) -> str | None:
    if session_name is None:
        return None
    stripped = session_name.strip()
    if stripped == "":
        return None
    return stripped


class Service(IService):
    def __init__(self, users, sessions, user_repository: IUserRepository):
        self.users = users
        self.sessions = sessions
        self.user_repository = user_repository

    def send(
        self,
        message: A2AMessage,
        aeko_messenger_factory,
        aeko_session_factory,
    ) -> str:
        """Deliver an agent message through the session service and return the approved reply."""
        id_external_user = _positive_int(message.id_external_user, "id_external_user")
        user = self.users.get_mongo_user(id_external_user)

        session_name = _effective_session_name(message.session_name)
        if session_name is None:
            id_session = ""
        else:
            try:
                user_sessions = self.sessions.get_user_sessions(user.id)
            except ValueError:
                user_sessions = []

            matching = [
                session
                for session in user_sessions
                if session.name == session_name
            ]
            if not matching:
                raise ValueError(
                    f"No session found with session_name {session_name!r} "
                    f"for user with id_user {user.id}."
                )
            id_session = matching[0].id

        result = self.sessions.send_message(
            id_session,
            message.text,
            user.id,
            aeko_messenger_factory,
            aeko_session_factory,
            self.user_repository,
        )
        return result.message.output
