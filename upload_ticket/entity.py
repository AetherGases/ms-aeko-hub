"""Define upload ticket domain entities."""

from dataclasses import dataclass


@dataclass(frozen=True)
class UploadTicket:
    ticket: str
    id_external_user: int
    name: str
    file_name: str
    file_type: str
    path: str | None
    state: str
    inventory_id: int | None
