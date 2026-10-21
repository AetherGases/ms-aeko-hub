"""Verify memory-generator worker behavior across window derivation, cache, and service."""

from datetime import datetime, timedelta

import pytest

from cmd.memory_generator_worker.constants import (
    CONVERSATION_MEMORY_FIELD,
    MEMORY_WORKER_ID_REQUEST,
    SESSION_INACTIVITY_MINUTES,
)
from cmd.memory_generator_worker.main import build_aeko_metrics_sink
from session.cache.cache import ICacheRepository
from session.cache.key import activity_key, window_key
from session.cache.repository import Repository as CacheRepository
from session.database import query as session_query
from session.database.repository import Repository as SessionRepository
from session.entity import Message, Session, SessionWindow
from session.memory_service import Service as MemoryService
from tests import fake_aeko
from tests.mongo_doubles import StubCollection, StubDatabase
from user.entity import UserMemory

ID_SESSION = "65a8b3d6c0f8e1d7f4b2c001"
ID_USER = "65a8b3d6c0f8e1d7f4b2c010"
SUBMITTED_AT = datetime(2026, 7, 26, 14, 30, 0)


class StubRedis:
    def __init__(self):
        self.values = {}
        self.expirations = {}
        self.deleted = []

    def set(self, key, value, ex=None):
        """Store a value and optionally mark it for expiry simulation."""
        self.values[key] = value
        if ex is None:
            self.expirations.pop(key, None)
        else:
            self.expirations[key] = ex

    def get(self, key):
        """Return the stored value for a key."""
        return self.values.get(key)

    def exists(self, key):
        """Return whether a key is present and not marked expired."""
        if key not in self.values:
            return 0
        if key in self.expirations and self.expirations[key] <= 0:
            return 0
        return 1

    def delete(self, key):
        """Remove a key from the simulated store."""
        self.deleted.append(key)
        self.values.pop(key, None)
        self.expirations.pop(key, None)

    def scan_iter(self, match=None, count=None):
        """Yield keys that match the supplied pattern."""
        prefix, suffix = match.split("*", 1)
        for key in self.values:
            if key.startswith(prefix) and key.endswith(suffix):
                yield key

    def ping(self):
        """Report that the simulated Redis instance is reachable."""
        return True

    def close(self):
        """Record closure of the simulated resource."""
        self.closed = True


class StubSummaryGenerator:
    def __init__(self):
        self.calls = []
        self.next_summary = "session recap"
        self.next_error = None

    def generate_summary(self, messages, *, id_request: str):
        """Record the summary call and return or raise its scripted result."""
        self.calls.append((messages, id_request))
        if self.next_error is not None:
            raise self.next_error
        return fake_aeko.AekoSummaryResponse(
            summary=self.next_summary,
            aeko_metrics=fake_aeko.AekoMetrics(
                id_request=id_request,
                latency=12,
                flow=fake_aeko.CONVERSATIONAL_FLOW,
                used_agents=[],
            ),
        )


class StubUserService:
    def __init__(self):
        self.memories = []

    def create_user_memory(self, user_memory: UserMemory):
        """Record a persisted user memory."""
        self.memories.append(user_memory)


class StubSessionRepository:
    def __init__(self, sessions=None, messages_by_session=None):
        self.sessions = list(sessions or [])
        self.messages_by_session = dict(messages_by_session or {})
        self.updated_since_calls = []

    def get_sessions_updated_since(self, since):
        """Return scripted sessions updated after the supplied instant."""
        self.updated_since_calls.append(since)
        return self.sessions

    def get_session_messages(self, id_session: str):
        """Return scripted messages for a session."""
        return self.messages_by_session.get(id_session, [])


def build_message(minutes_offset: int, label: str) -> Message:
    """Build a message submitted at a fixed offset from the base timestamp."""
    return Message(
        input=f"{label} input",
        output=f"{label} output",
        submitted_at=SUBMITTED_AT + timedelta(minutes=minutes_offset),
    )


def build_memory_service(
    session_repository,
    cache_repository,
    user_service,
    summary_generator,
    inactivity_minutes=SESSION_INACTIVITY_MINUTES,
    memory_field=CONVERSATION_MEMORY_FIELD,
    aeko_id_request=MEMORY_WORKER_ID_REQUEST,
):
    """Build a memory service with the worker defaults."""
    return MemoryService(
        session_repository,
        cache_repository,
        user_service,
        summary_generator,
        inactivity_minutes=inactivity_minutes,
        memory_field=memory_field,
        aeko_id_request=aeko_id_request,
    )


def test_session_window_returns_the_trailing_active_run():
    """Verify that session window returns the trailing active run."""
    messages = [
        build_message(0, "old"),
        build_message(25, "recent-a"),
        build_message(35, "recent-b"),
    ]

    window = SessionWindow.derive(messages, SESSION_INACTIVITY_MINUTES)

    assert [message.input for message in window] == [
        "recent-a input",
        "recent-b input",
    ]


def test_session_window_returns_an_empty_list_for_no_messages():
    """Verify that session window returns an empty list for no messages."""
    assert SessionWindow.derive([], SESSION_INACTIVITY_MINUTES) == []


def test_cache_repository_implements_the_cache_interface():
    """Verify that cache repository implements the cache interface."""
    assert issubclass(CacheRepository, ICacheRepository)


def test_set_window_persists_the_user_and_messages():
    """Verify that set window persists the user and messages."""
    redis = StubRedis()
    repository = CacheRepository(redis)
    messages = [build_message(0, "one")]

    repository.set_window(ID_SESSION, ID_USER, messages)
    window = repository.get_window(ID_SESSION)

    assert window.id_user == ID_USER
    assert len(window.messages) == 1
    assert window.messages[0].input == "one input"


def test_set_window_sets_an_expiry_of_at_least_inactivity_seconds():
    """Verify that set window stores the window with an expiry of at least inactivity seconds."""
    redis = StubRedis()
    repository = CacheRepository(redis)

    repository.set_window(ID_SESSION, ID_USER, [build_message(0, "one")])

    assert redis.expirations[window_key(ID_SESSION)] >= SESSION_INACTIVITY_MINUTES * 60


def test_list_expired_windows_returns_sessions_without_an_activity_key():
    """Verify that list expired windows returns sessions without an activity key."""
    redis = StubRedis()
    repository = CacheRepository(redis)
    repository.set_window(ID_SESSION, ID_USER, [build_message(0, "one")])

    assert repository.list_expired_windows() == [ID_SESSION]


def test_list_expired_windows_ignores_sessions_with_an_activity_key():
    """Verify that list expired windows ignores sessions with an activity key."""
    redis = StubRedis()
    repository = CacheRepository(redis)
    repository.set_window(ID_SESSION, ID_USER, [build_message(0, "one")])
    repository.set_activity(ID_SESSION, 60)

    assert repository.list_expired_windows() == []


def test_memory_service_harvests_an_expired_window_into_user_memory():
    """Verify that memory service harvests an expired window into user memory."""
    redis = StubRedis()
    cache_repository = CacheRepository(redis)
    cache_repository.set_window(ID_SESSION, ID_USER, [build_message(0, "one")])

    user_service = StubUserService()
    summary_generator = StubSummaryGenerator()
    service = build_memory_service(
        StubSessionRepository(),
        cache_repository,
        user_service,
        summary_generator,
    )

    service.run()

    assert len(user_service.memories) == 1
    memory = user_service.memories[0]
    assert memory.id_user == ID_USER
    assert memory.field == CONVERSATION_MEMORY_FIELD
    assert memory.description == "session recap"
    assert cache_repository.get_window(ID_SESSION) is None
    assert summary_generator.calls[0][1] == MEMORY_WORKER_ID_REQUEST


def test_memory_service_syncs_recent_sessions_before_refreshing_activity():
    """Verify that memory service syncs recent sessions before refreshing activity."""
    redis = StubRedis()
    cache_repository = CacheRepository(redis)
    messages = [build_message(0, "one")]
    session = Session(
        id=ID_SESSION,
        id_user=ID_USER,
        name="review",
        messages=[],
        updated_at=SUBMITTED_AT,
    )
    session_repository = StubSessionRepository(
        sessions=[session],
        messages_by_session={ID_SESSION: messages},
    )

    service = build_memory_service(
        session_repository,
        cache_repository,
        StubUserService(),
        StubSummaryGenerator(),
    )

    service.run()

    window = cache_repository.get_window(ID_SESSION)
    assert window is not None
    assert window.messages[0].input == "one input"
    assert redis.exists(activity_key(ID_SESSION)) == 1


def test_memory_service_harvests_before_syncing_recent_sessions():
    """Verify that memory service harvests before syncing recent sessions."""
    redis = StubRedis()
    cache_repository = CacheRepository(redis)
    cache_repository.set_window(ID_SESSION, ID_USER, [build_message(0, "stale")])

    recent_messages = [build_message(0, "fresh")]
    session = Session(
        id=ID_SESSION,
        id_user=ID_USER,
        name="review",
        messages=[],
        updated_at=SUBMITTED_AT,
    )
    session_repository = StubSessionRepository(
        sessions=[session],
        messages_by_session={ID_SESSION: recent_messages},
    )
    user_service = StubUserService()
    summary_generator = StubSummaryGenerator()
    service = build_memory_service(
        session_repository,
        cache_repository,
        user_service,
        summary_generator,
    )

    service.run()

    assert len(user_service.memories) == 1
    assert user_service.memories[0].description == "session recap"
    assert cache_repository.get_window(ID_SESSION).messages[0].input == "fresh input"


def test_get_sessions_updated_since_query_filters_by_updated_at():
    """Verify that get sessions updated since query filters by updated at."""
    since = SUBMITTED_AT

    query, projection = session_query.get_sessions_updated_since_query(since)

    assert query == {"updated_at": {"$gte": since}}
    assert projection == session_query.SESSION_PROJECTION


def test_repository_get_sessions_updated_since_returns_matching_sessions():
    """Verify that repository get sessions updated since returns matching sessions."""
    database = StubDatabase(
        session=StubCollection(
            find_result=[
                {
                    "_id": ID_SESSION,
                    "id_user": ID_USER,
                    "name": "review",
                    "created_at": SUBMITTED_AT,
                    "updated_at": SUBMITTED_AT,
                }
            ]
        )
    )
    repository = SessionRepository(database)

    sessions = repository.get_sessions_updated_since(SUBMITTED_AT)

    assert len(sessions) == 1
    assert sessions[0].id == ID_SESSION


def test_worker_metrics_sink_persists_memory_worker_id():
    """Verify that the worker sink stores metrics with the fixed request id."""
    database = StubDatabase(aeko_metrics=StubCollection())
    sink = build_aeko_metrics_sink(database)
    sink(
        fake_aeko.AekoMetrics(
            id_request=MEMORY_WORKER_ID_REQUEST,
            latency=12,
            flow=fake_aeko.CONVERSATIONAL_FLOW,
            used_agents=[],
        )
    )
    (document,) = database["aeko_metrics"].call_args("insert_one")[0]
    assert document["id_request"] == MEMORY_WORKER_ID_REQUEST
    assert document.get("id_external_company") is None


def test_fake_messenger_generate_summary_returns_a_scripted_summary(configured_sdk):
    """Verify that fake messenger generate summary returns a scripted summary."""
    fake_aeko.AekoMessenger.next_summary = "custom recap"
    messenger = fake_aeko.AekoMessenger(
        fake_aeko.AekoUser(id=ID_USER, id_external_user=1, role="analyst", usecase=""),
        [],
    )
    messages = [
        fake_aeko.AekoMessage(input="hello", output="world", submitted_at=SUBMITTED_AT)
    ]

    response = messenger.generate_summary(messages, id_request="req-1")

    assert response.summary == "custom recap"
    assert response.aeko_metrics.id_request == "req-1"
