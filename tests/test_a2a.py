"""Verify agent-to-agent send behavior and error handling."""

from datetime import datetime

import pytest

from cmd.api.integrations.a2a.entity import A2AMessage, A2A_RECIPIENT_AEKO, A2A_SENDER_CHATGPT
from cmd.api.integrations.a2a.service import Service
from session.entity import Message, SendMessageResult, Session
from session.session import GuardrailRejectedError
from user.entity import User

messenger_factory = object()
session_factory = object()


class StubUserService:
    def __init__(self, user_id="u1", raise_missing=False):
        self.user_id = user_id
        self.raise_missing = raise_missing
        self.calls = []

    def get_mongo_user(self, id_external_user):
        """Retrieve the stored user matching an external identifier."""
        self.calls.append(("get_mongo_user", id_external_user))
        if self.raise_missing:
            raise ValueError(
                f"User with id_external_user {id_external_user} not found."
            )
        return User(
            id=self.user_id,
            id_external_user=id_external_user,
            role="analyst",
            usecase="report_generation",
        )

    def get_mongo_user_or_create(self, id_external_user, role, usecase):
        """Return the stored user or create one with the supplied profile fields."""
        try:
            return self.get_mongo_user(id_external_user)
        except ValueError:
            self.calls.append(("create_user", id_external_user, role, usecase))
            self.raise_missing = False
            return User(
                id=self.user_id,
                id_external_user=id_external_user,
                role=role,
                usecase=usecase,
            )


class StubSessionService:
    def __init__(self):
        self.user_sessions = None
        self.sent = []
        self.next_error = None

    def get_user_sessions(self, id_user):
        """Retrieve the sessions belonging to a user."""
        if self.user_sessions is None:
            raise ValueError(f"No sessions found for user with id_user {id_user}.")
        return [session for session in self.user_sessions if session.id_user == id_user]

    def send_message(
        self,
        id_session,
        input,
        id_user,
        aeko_messenger_factory,
        aeko_session_factory,
        user_repository,
    ):
        """Record the send call and return a scripted message."""
        if self.next_error is not None:
            raise self.next_error
        self.sent.append(
            {
                "id_session": id_session,
                "input": input,
                "id_user": id_user,
                "aeko_messenger_factory": aeko_messenger_factory,
                "aeko_session_factory": aeko_session_factory,
                "user_repository": user_repository,
            }
        )
        return SendMessageResult(
            Message(
                input=input,
                output="Aeko reply",
                submitted_at=datetime(2026, 10, 4, 12, 0, 0),
            ),
            Session(
                id=id_session or "s-new",
                id_user=id_user,
                name="Weekly emissions review",
                messages=[],
            ),
        )


class StubUserRepository:
    pass


def stubs(user_id="u1"):
    """Build user, session, and repository stubs for A2A send tests."""
    users = StubUserService(user_id=user_id)
    sessions = StubSessionService()
    user_repository = StubUserRepository()
    return users, sessions, user_repository


def test_send_creates_a_session_when_session_name_is_omitted():
    """Verify that send starts a new session when no session name is supplied."""
    users, sessions, user_repository = stubs(user_id="u1")
    output = Service(users, sessions, user_repository).send(
        A2AMessage("chatgpt", "aeko", "Hello Aeko", 12345),
        messenger_factory,
        session_factory,
    )
    assert output == "Aeko reply"
    assert sessions.sent[0]["id_session"] in ("", None)
    assert sessions.sent[0]["id_user"] == "u1"
    assert sessions.sent[0]["input"] == "Hello Aeko"


def test_send_continues_the_named_session_owned_by_the_user():
    """Verify that send reuses an existing session when the name belongs to the user."""
    users, sessions, user_repository = stubs(user_id="u1")
    sessions.user_sessions = [
        Session(
            id="s1",
            id_user="u1",
            name="Weekly emissions review",
            messages=[],
        )
    ]
    Service(users, sessions, user_repository).send(
        A2AMessage(
            "chatgpt",
            "aeko",
            "Follow up",
            12345,
            session_name="Weekly emissions review",
        ),
        messenger_factory,
        session_factory,
    )
    assert sessions.sent[0]["id_session"] == "s1"


def test_send_rejects_another_users_session_name():
    """Verify that send rejects a session name that belongs to another user."""
    users, sessions, user_repository = stubs(user_id="u1")
    sessions.user_sessions = [
        Session(
            id="s2",
            id_user="u2",
            name="Weekly emissions review",
            messages=[],
        )
    ]
    with pytest.raises(ValueError, match="session_name"):
        Service(users, sessions, user_repository).send(
            A2AMessage(
                "chatgpt",
                "aeko",
                "Follow up",
                12345,
                session_name="Weekly emissions review",
            ),
            messenger_factory,
            session_factory,
        )
    assert sessions.sent == []


def test_send_propagates_guardrail_rejection():
    """Verify that send propagates guardrail rejection without persisting a reply."""
    users, sessions, user_repository = stubs(user_id="u1")
    sessions.next_error = GuardrailRejectedError("No answer...")
    with pytest.raises(GuardrailRejectedError):
        Service(users, sessions, user_repository).send(
            A2AMessage("chatgpt", "aeko", "Hello Aeko", 12345),
            messenger_factory,
            session_factory,
        )


def test_send_rejects_an_unknown_user():
    """Verify that send rejects an unknown external user before calling the session service."""
    users, sessions, user_repository = stubs(user_id="u1")
    users.raise_missing = True
    with pytest.raises(ValueError, match="not found"):
        Service(users, sessions, user_repository).send(
            A2AMessage("chatgpt", "aeko", "Hello Aeko", 12345),
            messenger_factory,
            session_factory,
        )
    assert sessions.sent == []


@pytest.mark.parametrize("id_external_user", [True, False, 0, -1, None, "abc", ""])
def test_send_rejects_invalid_id_external_user(id_external_user):
    """Verify that send rejects invalid id_external_user values before lookup."""
    users, sessions, user_repository = stubs(user_id="u1")
    with pytest.raises(ValueError, match="id_external_user"):
        Service(users, sessions, user_repository).send(
            A2AMessage("chatgpt", "aeko", "Hello Aeko", id_external_user),
            messenger_factory,
            session_factory,
        )
    assert users.calls == []
    assert sessions.sent == []


def test_send_normalizes_numeric_string_id_external_user():
    """Verify that send normalizes numeric string id_external_user values."""
    users, sessions, user_repository = stubs(user_id="u1")
    Service(users, sessions, user_repository).send(
        A2AMessage("chatgpt", "aeko", "Hello Aeko", "12345"),
        messenger_factory,
        session_factory,
    )
    assert users.calls == [("get_mongo_user", 12345)]


@pytest.mark.parametrize("session_name", ["", "   "])
def test_send_creates_a_session_when_session_name_is_blank(session_name):
    """Verify that blank session_name values start a new session like None."""
    users, sessions, user_repository = stubs(user_id="u1")
    sessions.user_sessions = [
        Session(
            id="s1",
            id_user="u1",
            name="Weekly emissions review",
            messages=[],
        )
    ]
    Service(users, sessions, user_repository).send(
        A2AMessage(
            "chatgpt",
            "aeko",
            "Hello Aeko",
            12345,
            session_name=session_name,
        ),
        messenger_factory,
        session_factory,
    )
    assert sessions.sent[0]["id_session"] in ("", None)
