"""Coordinate upload ticket lifecycle operations."""

import secrets
from urllib.parse import urlparse

from cmd.api.integrations.cloudinary_api import get_upload_signature

from upload_ticket.constants import (
    STATE_CONSUMED,
    STATE_UPLOADED,
    STATE_WAITING_FOR_UPLOAD,
    VALID_FILE_TYPES,
    _CLOUDINARY_ALLOWED_HOSTS,
)
from upload_ticket.entity import UploadTicket
from upload_ticket.upload_ticket import IService


def _assert_allowed_cloudinary_path(path: str) -> None:
    """Reject a storage path that is not an https Cloudinary CDN URL."""
    parsed = urlparse(path)
    if parsed.scheme != "https" or parsed.username or parsed.password:
        raise ValueError("Upload path is not allowed.")
    host = parsed.hostname
    if not isinstance(host, str) or host.strip() == "":
        raise ValueError("Upload path is not allowed.")
    lowered = host.lower().rstrip(".")
    if lowered not in _CLOUDINARY_ALLOWED_HOSTS:
        raise ValueError("Upload path is not allowed.")
    prefix = parsed.path or ""
    if ".." in prefix or "/upload/" not in prefix:
        raise ValueError("Upload path is not allowed.")


class Service(IService):
    def __init__(self, repository):
        """Bind the upload-ticket cache repository."""
        self.repository = repository

    def create(
        self,
        id_external_user: int,
        name: str,
        file_name: str,
        file_type: str,
    ) -> UploadTicket:
        """Create a new upload ticket for an inventory file."""
        if file_type not in VALID_FILE_TYPES:
            raise ValueError(f"file_type must be one of {sorted(VALID_FILE_TYPES)}.")

        ticket_id = secrets.token_urlsafe(32)
        ticket = UploadTicket(
            ticket=ticket_id,
            id_external_user=id_external_user,
            name=name,
            file_name=file_name,
            file_type=file_type,
            path=None,
            state=STATE_WAITING_FOR_UPLOAD,
            inventory_id=None,
        )
        self.repository.save(ticket)
        return ticket

    def signature_for(self, id_external_user: int, ticket: str) -> dict:
        """Return the Cloudinary upload signature for a ticket."""
        stored = self._load(id_external_user, ticket, allow_consumed=False)
        return get_upload_signature(stored.file_type)

    def confirm_path(
        self,
        id_external_user: int,
        ticket: str,
        path: str,
    ) -> UploadTicket:
        """Record the uploaded file path and mark the ticket as uploaded."""
        stored = self._load(id_external_user, ticket, allow_consumed=False)
        if stored.path is not None:
            raise ValueError("Upload ticket path is already set.")
        _assert_allowed_cloudinary_path(path)

        updated = UploadTicket(
            ticket=stored.ticket,
            id_external_user=stored.id_external_user,
            name=stored.name,
            file_name=stored.file_name,
            file_type=stored.file_type,
            path=path,
            state=STATE_UPLOADED,
            inventory_id=stored.inventory_id,
        )
        self.repository.save(updated)
        return updated

    def get(self, id_external_user: int, ticket: str) -> UploadTicket:
        """Return an upload ticket owned by the given user."""
        return self._load(id_external_user, ticket, allow_consumed=True)

    def mark_consumed(
        self,
        id_external_user: int,
        ticket: str,
        inventory_id: int,
    ) -> UploadTicket:
        """Mark an uploaded ticket as consumed after inventory creation."""
        stored = self._load(id_external_user, ticket, allow_consumed=False)
        if stored.state != STATE_UPLOADED:
            raise ValueError(
                "Upload ticket must be uploaded before it can be consumed."
            )

        updated = UploadTicket(
            ticket=stored.ticket,
            id_external_user=stored.id_external_user,
            name=stored.name,
            file_name=stored.file_name,
            file_type=stored.file_type,
            path=stored.path,
            state=STATE_CONSUMED,
            inventory_id=inventory_id,
        )
        self.repository.save(updated)
        self.repository.append_created_id(id_external_user, inventory_id)
        return updated

    def created_inventory_ids(self, id_external_user: int) -> list[int]:
        """Return inventory identifiers created from upload tickets for a user."""
        return self.repository.get_created_ids(id_external_user)

    def record_created_inventory(
        self, id_external_user: int, inventory_id: int
    ) -> None:
        """Record an inventory created through ChatGPT ingest for later analysis."""
        self.repository.append_created_id(id_external_user, inventory_id)

    def _load(
        self,
        id_external_user: int,
        ticket: str,
        *,
        allow_consumed: bool,
    ) -> UploadTicket:
        """Load a ticket owned by the user, or raise if it is missing."""
        stored = self.repository.get(ticket)
        if stored is None or stored.id_external_user != id_external_user:
            raise ValueError("Upload ticket not found.")
        if not allow_consumed and stored.state == STATE_CONSUMED:
            raise ValueError("Upload ticket not found.")
        return stored
