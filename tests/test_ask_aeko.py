"""Verify the typed ChatGPT-to-Aeko messaging tool."""

import pytest
from langchain_core.tools import Tool

from cmd.api.integrations.a2a.entity import (
    A2AMessage,
    A2A_RECIPIENT_AEKO,
    A2A_SENDER_CHATGPT,
)
from cmd.api.tools import ask_aeko as ask_aeko_tools
from cmd.api.tools import constants as tool_constants
from session.session import GuardrailRejectedError


COMPANY_ID = 90


class StubA2A:
    """Record sent messages and return or raise a scripted result."""

    def __init__(self):
        self.calls = []
        self.result = "Aeko response"
        self.error = None

    def send(self, message, aeko_messenger_factory, aeko_session_factory):
        """Record one send call and return the scripted result."""

        self.calls.append((message, aeko_messenger_factory, aeko_session_factory))
        if self.error is not None:
            raise self.error
        return self.result


@pytest.fixture
def configured_tool():
    """Bind fresh A2A dependencies and conversation identity for each test."""

    from cmd.api.acl.open_ai.identity import (
        bind_id_external_company,
        bind_id_external_user,
        reset_id_external_company,
        reset_id_external_user,
    )

    a2a = StubA2A()
    messenger_factory = object()
    session_factory = object()
    ask_aeko_tools.configure(
        a2a=a2a,
        aeko_messenger_factory=messenger_factory,
        aeko_session_factory=session_factory,
    )
    user_token = bind_id_external_user(12345)
    company_token = bind_id_external_company(COMPANY_ID)
    try:
        yield a2a, messenger_factory, session_factory
    finally:
        reset_id_external_company(company_token)
        reset_id_external_user(user_token)
        ask_aeko_tools.configure()


def test_ask_aeko_sends_message_and_returns_reply(configured_tool):
    """Send the required A2A message and return its reply text."""

    a2a, messenger_factory, session_factory = configured_tool

    result = ask_aeko_tools.ask_aeko(12345, COMPANY_ID, "Hello Aeko")

    assert result == "Aeko response"
    assert len(a2a.calls) == 1
    message, sent_messenger_factory, sent_session_factory = a2a.calls[0]
    assert message.sender == A2A_SENDER_CHATGPT
    assert message.recipient == A2A_RECIPIENT_AEKO
    assert message.text == "Hello Aeko"
    assert message.id_external_user == 12345
    assert message.session_name is None
    assert sent_messenger_factory is messenger_factory
    assert sent_session_factory is session_factory


@pytest.mark.parametrize("bad", [True, False, 0, -1])
def test_ask_aeko_rejects_invalid_user_before_send(configured_tool, bad):
    """Reject bool and non-positive user identifiers without sending."""

    a2a, _, _ = configured_tool

    with pytest.raises(ValueError, match="id_external_user"):
        ask_aeko_tools.ask_aeko(bad, COMPANY_ID, "Hello Aeko")

    assert a2a.calls == []


@pytest.mark.parametrize("bad", [True, False, 0, -1, None])
def test_ask_aeko_rejects_invalid_company_before_send(configured_tool, bad):
    """Reject bool and non-positive company identifiers without sending."""

    a2a, _, _ = configured_tool

    with pytest.raises(ValueError, match="id_external_company"):
        ask_aeko_tools.ask_aeko(12345, bad, "Hello Aeko")

    assert a2a.calls == []


@pytest.mark.parametrize("bad", ["", "   "])
def test_ask_aeko_rejects_empty_input_before_send(configured_tool, bad):
    """Reject empty message input without sending."""

    a2a, _, _ = configured_tool

    with pytest.raises(ValueError, match="input"):
        ask_aeko_tools.ask_aeko(12345, COMPANY_ID, bad)

    assert a2a.calls == []


def test_ask_aeko_rejects_a_company_that_does_not_match_the_token(
    configured_tool, monkeypatch
):
    """Reject a company id that does not match the OAuth token."""

    a2a, _, _ = configured_tool
    import cmd.api.acl.open_ai.identity as identity

    monkeypatch.setattr(identity, "current_id_external_company", lambda: 90)

    with pytest.raises(ValueError, match="OAuth token"):
        ask_aeko_tools.ask_aeko(12345, 91, "Hello Aeko")

    assert a2a.calls == []


def test_ask_aeko_forwards_named_session(configured_tool):
    """Forward a supplied conversation session name on the message."""

    a2a, _, _ = configured_tool

    ask_aeko_tools.ask_aeko(
        12345,
        COMPANY_ID,
        "Hello Aeko",
        session_name="Weekly emissions review",
    )

    assert a2a.calls[0][0].session_name == "Weekly emissions review"


@pytest.mark.parametrize("session_name", [None, "", "   "])
def test_ask_aeko_omits_missing_or_blank_session(configured_tool, session_name):
    """Send no session name when it is omitted, null, or blank."""

    a2a, _, _ = configured_tool

    ask_aeko_tools.ask_aeko(
        12345,
        COMPANY_ID,
        "Hello Aeko",
        session_name=session_name,
    )

    assert a2a.calls[0][0].session_name is None


def test_ask_aeko_propagates_guardrail_rejection(configured_tool):
    """Propagate the original guardrail rejection from A2A unchanged."""

    a2a, _, _ = configured_tool
    rejection = GuardrailRejectedError("No approved response")
    a2a.error = rejection

    with pytest.raises(GuardrailRejectedError) as raised:
        ask_aeko_tools.ask_aeko(12345, COMPANY_ID, "Hello Aeko")

    assert raised.value is rejection


def test_ask_aeko_raises_when_dependencies_are_unconfigured():
    """Raise when A2A or either required factory has not been bound."""

    from cmd.api.acl.open_ai.identity import (
        bind_id_external_company,
        bind_id_external_user,
        reset_id_external_company,
        reset_id_external_user,
    )

    a2a = StubA2A()
    dependencies = [
        {},
        {
            "a2a": a2a,
            "aeko_messenger_factory": object(),
        },
        {
            "a2a": a2a,
            "aeko_session_factory": object(),
        },
    ]
    user_token = bind_id_external_user(12345)
    company_token = bind_id_external_company(COMPANY_ID)
    try:
        for configured in dependencies:
            ask_aeko_tools.configure(**configured)
            with pytest.raises(RuntimeError):
                ask_aeko_tools.ask_aeko(12345, COMPANY_ID, "Hello Aeko")
    finally:
        reset_id_external_company(company_token)
        reset_id_external_user(user_token)

    assert a2a.calls == []
    ask_aeko_tools.configure()


def test_ask_aeko_rejects_unbound_company():
    """Verify that ask_aeko raises when company identity is unbound."""

    a2a = StubA2A()
    ask_aeko_tools.configure(
        a2a=a2a,
        aeko_messenger_factory=object(),
        aeko_session_factory=object(),
    )
    try:
        with pytest.raises(RuntimeError, match="ChatGPT company identity is not bound"):
            ask_aeko_tools.ask_aeko(12345, COMPANY_ID, "Hello Aeko")
    finally:
        ask_aeko_tools.configure()

    assert a2a.calls == []


def test_get_ask_aeko_tools_exposes_typed_tool(configured_tool):
    """Expose one typed tool with the configured description and schema."""

    from cmd.api.acl.open_ai.wrappers import _strip_identity_from_description

    tools = ask_aeko_tools.get_ask_aeko_tools()

    assert len(tools) == 1
    tool = tools[0]
    assert isinstance(tool, Tool)
    assert tool.name == "ask_aeko"
    assert tool.description == _strip_identity_from_description(
        tool_constants.ASK_AEKO_DESCRIPTION
    )
    assert set(tool.args) == {
        "input",
        "session_name",
    }
    assert "session_name" not in tool.args_schema.model_json_schema()["required"]
