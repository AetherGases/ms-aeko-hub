"""Persist and retrieve upload tickets through Redis."""

import json

from upload_ticket.cache.key import created_ids_key, upload_key
from upload_ticket.constants import INVENTORY_UPLOAD_TICKET_TTL_SECONDS
from upload_ticket.entity import UploadTicket


class Repository:
    def __init__(self, redis_client):
        """Bind the Redis client used for upload tickets."""
        self.redis = redis_client

    def save(self, ticket: UploadTicket) -> None:
        """Persist an upload ticket with the configured TTL."""
        document = {
            "ticket": ticket.ticket,
            "id_external_user": ticket.id_external_user,
            "name": ticket.name,
            "file_name": ticket.file_name,
            "file_type": ticket.file_type,
            "path": ticket.path,
            "state": ticket.state,
            "inventory_id": ticket.inventory_id,
        }
        self.redis.set(
            upload_key(ticket.ticket),
            json.dumps(document),
            ex=INVENTORY_UPLOAD_TICKET_TTL_SECONDS,
        )

    def get(self, ticket: str) -> UploadTicket | None:
        """Retrieve an upload ticket by its opaque identifier."""
        payload = self.redis.get(upload_key(ticket))
        if payload is None:
            return None

        decoded = payload.decode() if isinstance(payload, bytes) else payload
        document = json.loads(decoded)
        return UploadTicket(
            ticket=document["ticket"],
            id_external_user=document["id_external_user"],
            name=document["name"],
            file_name=document["file_name"],
            file_type=document["file_type"],
            path=document["path"],
            state=document["state"],
            inventory_id=document["inventory_id"],
        )

    def get_created_ids(self, id_external_user: int) -> list[int]:
        """Return inventory ids created from upload tickets for a user."""
        payload = self.redis.lrange(created_ids_key(id_external_user), 0, -1)
        ids = []
        for item in payload or []:
            decoded = item.decode() if isinstance(item, bytes) else item
            ids.append(int(decoded))
        return ids

    def append_created_id(self, id_external_user: int, inventory_id: int) -> None:
        """Atomically append an inventory id and refresh the created-inventory TTL."""
        key = created_ids_key(id_external_user)
        pipeline = getattr(self.redis, "pipeline", None)
        if callable(pipeline):
            pipe = pipeline()
            pipe.rpush(key, str(inventory_id))
            pipe.expire(key, INVENTORY_UPLOAD_TICKET_TTL_SECONDS)
            pipe.execute()
            return
        self.redis.rpush(key, str(inventory_id))
        self.redis.expire(key, INVENTORY_UPLOAD_TICKET_TTL_SECONDS)
