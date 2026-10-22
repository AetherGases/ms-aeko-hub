"""Define the domain entities for agent-to-agent messaging."""

from dataclasses import dataclass

from cmd.api.integrations.a2a.constants import A2A_RECIPIENT_AEKO, A2A_SENDER_CHATGPT


@dataclass(frozen=True)
class A2AMessage:
    sender: str
    recipient: str
    text: str
    id_external_user: int
    session_name: str | None = None
