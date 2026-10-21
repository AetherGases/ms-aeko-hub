"""Verify upload ticket lifecycle and Redis persistence."""

import pytest

from tests.conftest import FakeRedis
from upload_ticket.cache.key import created_ids_key, upload_key
from upload_ticket.cache.repository import Repository
from upload_ticket.constants import INVENTORY_UPLOAD_TICKET_TTL_SECONDS
from upload_ticket.service import Service

CLOUDINARY_PATH = "https://res.cloudinary.com/meu-cloud/raw/upload/v1/uploads/file.xlsx"
CLOUDINARY_PATH_TWO = "https://res.cloudinary.com/meu-cloud/raw/upload/v1/uploads/file2.xlsx"


class ListRedis(FakeRedis):
    """FakeRedis with list commands used by the created-inventory index."""

    def rpush(self, key, *values):
        """Append values to a list stored at key."""
        items = self.values.get(key)
        if items is None:
            items = []
            self.values[key] = items
        elif not isinstance(items, list):
            items = [items]
            self.values[key] = items
        items.extend(values)
        return len(items)

    def lrange(self, key, start, end):
        """Return a slice of the list stored at key."""
        items = self.values.get(key, [])
        if not isinstance(items, list):
            return []
        if end == -1:
            return list(items[start:])
        return list(items[start : end + 1])

    def expire(self, key, seconds):
        """Attach a TTL to an existing key."""
        if key not in self.values:
            return False
        self.expirations[key] = seconds
        return True

    def pipeline(self):
        """Return a pipeline that applies rpush and expire atomically on execute."""
        return ListRedisPipeline(self)


class ListRedisPipeline:
    """Record list mutations and apply them when execute is called."""

    def __init__(self, redis):
        self.redis = redis
        self.ops = []

    def rpush(self, key, *values):
        """Queue an rpush for execute."""
        self.ops.append(("rpush", key, values))
        return self

    def expire(self, key, seconds):
        """Queue an expire for execute."""
        self.ops.append(("expire", key, seconds))
        return self

    def execute(self):
        """Apply queued list mutations in order."""
        results = []
        for op in self.ops:
            if op[0] == "rpush":
                results.append(self.redis.rpush(op[1], *op[2]))
            elif op[0] == "expire":
                results.append(self.redis.expire(op[1], op[2]))
        self.ops = []
        return results


@pytest.fixture
def redis():
    """Provide an isolated in-memory Redis double with list commands."""
    return ListRedis()


@pytest.fixture
def repository(redis):
    """Provide an upload ticket repository backed by FakeRedis."""
    return Repository(redis)


@pytest.fixture
def service(repository, monkeypatch):
    """Provide an upload ticket service with Cloudinary stubbed out."""
    monkeypatch.setattr(
        "upload_ticket.service.get_upload_signature",
        lambda file_type: {"signature": file_type},
    )
    return Service(repository)


def test_create_returns_opaque_ticket_with_waiting_state(service, redis):
    """Persist a new ticket with waiting state and TTL."""
    ticket = service.create(42, "inventory", "file.xlsx", "XLSX")

    assert ticket.ticket
    assert ticket.state == "waiting_for_upload"
    assert ticket.path is None
    assert ticket.inventory_id is None
    assert ticket.id_external_user == 42
    assert ticket.name == "inventory"
    assert ticket.file_name == "file.xlsx"
    assert ticket.file_type == "XLSX"

    key = upload_key(ticket.ticket)
    assert key in redis.values
    assert redis.expirations[key] == INVENTORY_UPLOAD_TICKET_TTL_SECONDS


def test_signature_for_calls_get_upload_signature_with_file_type(service, monkeypatch):
    """Return Cloudinary signature JSON for the ticket file type."""
    created = service.create(42, "inventory", "file.xlsx", "XLSX")
    calls = []

    monkeypatch.setattr(
        "upload_ticket.service.get_upload_signature",
        lambda file_type: calls.append(file_type) or {"sig": 1},
    )

    result = service.signature_for(42, created.ticket)

    assert calls == ["XLSX"]
    assert result == {"sig": 1}


def test_confirm_path_once(service):
    """Store the upload path and move the ticket to uploaded state."""
    created = service.create(42, "inventory", "file.xlsx", "XLSX")

    updated = service.confirm_path(42, created.ticket, CLOUDINARY_PATH)

    assert updated.path == CLOUDINARY_PATH
    assert updated.state == "uploaded"


def test_confirm_path_rejects_second_path(service):
    """Reject overwriting a path that was already confirmed."""
    created = service.create(42, "inventory", "file.xlsx", "XLSX")
    service.confirm_path(42, created.ticket, CLOUDINARY_PATH)

    with pytest.raises(ValueError, match="path"):
        service.confirm_path(42, created.ticket, CLOUDINARY_PATH_TWO)


def test_confirm_path_rejects_arbitrary_path(service):
    """Verify that confirm_path rejects a path outside the Cloudinary host/prefix allowlist."""
    created = service.create(42, "inventory", "file.xlsx", "XLSX")

    with pytest.raises(ValueError, match="path"):
        service.confirm_path(42, created.ticket, "http://127.0.0.1/latest/meta-data/")
    with pytest.raises(ValueError, match="path"):
        service.confirm_path(42, created.ticket, "https://inventory.test/api/inventories")
    with pytest.raises(ValueError, match="path"):
        service.confirm_path(42, created.ticket, "/internal/uploads/file.xlsx")

    assert service.get(42, created.ticket).path is None


def test_operations_reject_other_user(service):
    """Hide ticket existence from users who do not own it."""
    created = service.create(42, "inventory", "file.xlsx", "XLSX")

    with pytest.raises(ValueError, match="not found"):
        service.get(99, created.ticket)
    with pytest.raises(ValueError, match="not found"):
        service.signature_for(99, created.ticket)
    with pytest.raises(ValueError, match="not found"):
        service.confirm_path(99, created.ticket, CLOUDINARY_PATH)


def test_mark_consumed_and_created_inventory_ids(service):
    """Append inventory ids after a successful consume."""
    created = service.create(42, "inventory", "file.xlsx", "XLSX")
    service.confirm_path(42, created.ticket, CLOUDINARY_PATH)

    consumed = service.mark_consumed(42, created.ticket, 501)

    assert consumed.state == "consumed"
    assert consumed.inventory_id == 501
    assert service.created_inventory_ids(42) == [501]

    created2 = service.create(42, "inventory-two", "file2.xlsx", "IMAGE")
    service.confirm_path(42, created2.ticket, CLOUDINARY_PATH_TWO)
    service.mark_consumed(42, created2.ticket, 502)

    assert service.created_inventory_ids(42) == [501, 502]


def test_mark_consumed_rejects_waiting_state(service):
    """Reject consume while the ticket is still waiting for upload."""
    created = service.create(42, "inventory", "file.xlsx", "XLSX")

    with pytest.raises(ValueError):
        service.mark_consumed(42, created.ticket, 501)


def test_record_created_inventory_appends_id(service):
    """Append inventory ids created through ChatGPT ingest without a ticket."""
    service.record_created_inventory(42, 501)

    assert service.created_inventory_ids(42) == [501]

    service.record_created_inventory(42, 502)

    assert service.created_inventory_ids(42) == [501, 502]


def test_append_created_id_sets_ttl(repository, redis):
    """Verify that the created-inventory Redis index is written with a TTL."""
    repository.append_created_id(42, 501)

    key = created_ids_key(42)
    assert repository.get_created_ids(42) == [501]
    assert redis.expirations[key] == INVENTORY_UPLOAD_TICKET_TTL_SECONDS

    repository.append_created_id(42, 502)

    assert repository.get_created_ids(42) == [501, 502]
    assert redis.expirations[key] == INVENTORY_UPLOAD_TICKET_TTL_SECONDS
