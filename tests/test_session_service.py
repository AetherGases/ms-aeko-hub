"""Verify session service behavior and error handling."""

import inspect
from datetime import datetime, timedelta

import pytest

from session.entity import Message, Session, SessionWindow
from session.service import Service, _metric_company
from session.session import GuardrailRejectedError, IService
from internal.shared.event_tracking import (
    bind_id_request,
    set_aeko_metrics_sink,
    unbind_id_request,
)
from user.entity import User, UserMemory

ID_SESSION = "s1"
ID_USER = "u1"
SUBMITTED_AT = datetime(2026, 7, 26, 14, 30, 0)


REVIEW_FAILURE = "no answer approved by the output guardrail or the response checker"

USER = User(
    id=ID_USER,
    id_external_user=12345,
    role="analyst",
    usecase="report_generation",
    id_external_company=90,
)


class StubTurn:
    """One entry of `session.messages`, as `AekoMessageResponse.message`."""

    def __init__(self, input, output, submitted_at=None):
        self.input = input
        self.output = output
        self.submitted_at = submitted_at


class StubMetrics:
    """Stands in for the `AekoMetrics` the SDK reports a request with."""

    def __init__(self, id_request="", error_description=None, flow="conversational"):
        self.id_request = id_request
        self.latency = 12
        self.error_description = error_description
        self.flow = flow
        self.used_agents = []


class StubResponse:
    def __init__(
        self,
        message,
        aeko_metrics=None,
        approved=True,
        agents_called=None,
        guardrail_retries=0,
    ):
        self.message = message
        self.aeko_metrics = aeko_metrics or StubMetrics()
        self.id_session = ID_SESSION
        self.id_user = ID_USER
        self.approved = approved
        self.agents_called = agents_called or ["FAQ"]
        self.guardrail_retries = guardrail_retries


class StubMessenger:
    def __init__(self, user, memories, turn=None, approved=True, error=None):
        self.user = user
        self.memories = memories
        self.turn = turn
        self.approved = approved
        self.error = error
        self.sent = []

    def send_message(self, message, session, *, id_request):
        """Record the conversation call and return or raise its scripted result."""
        self.sent.append((message, session, id_request))
        if self.error is not None:
            raise self.error

        if not self.approved:
            rejection = GuardrailRejectedError(REVIEW_FAILURE)
            rejection.aeko_metrics = StubMetrics(
                id_request=id_request,
                error_description=REVIEW_FAILURE,
            )
            raise rejection

        turn = self.turn or StubTurn(input=message, output=f"echo: {message}")
        return StubResponse(
            turn,
            aeko_metrics=StubMetrics(id_request=id_request),
            approved=True,
        )


class StubMessengerFactory:
    """Stands in for the factory the lifespan publishes on `app.state`."""

    def __init__(self, turn=None, approved=True, error=None):
        self.turn = turn
        self.approved = approved
        self.error = error
        self.built = []

    def __call__(self, user, memories):
        messenger = StubMessenger(user, memories, self.turn, self.approved, self.error)
        self.built.append(messenger)
        return messenger

    @property
    def last(self):
        """Return the most recently created test instance."""
        return self.built[-1]


class StubSessionDocument:
    """Stands in for the `AekoSession` the factory builds from the entity."""

    def __init__(self, session):
        self.id = session.id
        self.id_user = session.id_user
        self.name = session.name
        self.messages = list(session.messages)


class StubSessionFactory:
    def __init__(self):
        self.built = []

    def __call__(self, session):
        document = StubSessionDocument(session)
        self.built.append(document)
        return document

    @property
    def last(self):
        """Return the most recently created test instance."""
        return self.built[-1]


class FakeSessionRepository:
    def __init__(self, sessions=None, messages=None, messages_count=0, error=None):
        self.sessions = sessions or {
            ID_SESSION: Session(id=ID_SESSION, id_user=ID_USER, name="", messages=[])
        }
        self.messages = messages or {}
        self.messages_count = messages_count
        self.error = error
        self.saved = []
        self.names = {}
        self.created_for = []
        self.message_lookups = []

    def _guard(self):
        if self.error is not None:
            raise self.error

    def get_user_sessions(self, id_user):
        """Retrieve the sessions belonging to a user."""
        self._guard()
        return [
            session for session in self.sessions.values() if session.id_user == id_user
        ]

    def get_session(self, id_session):
        """Retrieve a session by its internal identifier."""
        self._guard()
        session = self.sessions.get(id_session)
        if session is None:
            raise ValueError(f"No session found with id_session {id_session}.")
        return session

    def get_session_messages(self, id_session):
        """Retrieve the stored messages for a session."""
        self._guard()
        self.message_lookups.append(id_session)
        return self.messages.get(id_session, [])

    def get_session_messages_count(self, id_session):
        """Return the number of messages stored in a session."""
        self._guard()
        return self.messages_count

    def create_session(self, id_user, user_repository):
        """Create an empty session for an existing user and return its identifier."""
        self._guard()
        self.created_for.append((id_user, user_repository))
        id_session = f"session-{len(self.sessions) + 1}"
        self.sessions[id_session] = Session(
            id=id_session, id_user=id_user, name="", messages=[]
        )
        return id_session

    def save_message(self, id_session, message):
        """Append a message to the session and update its modification timestamp."""
        self._guard()
        self.saved.append((id_session, message))

    def update_name(self, id_session, name):
        """Update the session name and modification timestamp."""
        self._guard()
        self.names[id_session] = name

    def delete_session(self, id_session):
        """Delete a session that holds at most one message."""
        self.sessions.pop(id_session)


class StubUserRepository:
    def __init__(self, user=USER, memories=None):
        self.user = user
        self.memories = list(memories or [])

    def get_user(self, id_external_user):
        """Retrieve a user by external identifier."""
        return self.user

    def get_user_by_id(self, id_user):
        """Retrieve a user by internal identifier, returning None when absent."""
        return self.user

    def get_user_memories(self, id_user):
        """Retrieve the memories stored for a user."""
        return self.memories

    def create_user_memory(self, user_memory):
        """Persist a memory associated with a user."""
        self.memories.append(user_memory)


class StubCacheRepository:
    def __init__(self, windows=None):
        self.windows = dict(windows or {})
        self.activity = {}
        self.get_window_calls = []

    def get_window(self, id_session):
        """Retrieve the stored conversation window for a session."""
        self.get_window_calls.append(id_session)
        return self.windows.get(id_session)

    def set_window(self, id_session, id_user, messages):
        """Persist the current conversation window for a session."""
        self.windows[id_session] = SessionWindow(id_user, list(messages))

    def set_activity(self, id_session, ttl_seconds):
        """Refresh the inactivity marker for a session."""
        self.activity[id_session] = ttl_seconds

    def delete_window(self, id_session):
        """Remove the stored conversation window for a session."""
        self.windows.pop(id_session, None)

    def list_expired_windows(self):
        """Return session identifiers whose activity key expired while a window remains."""
        return []


def build_service(cache_repository=None, inactivity_minutes=20, **kwargs):
    """Build a domain service with configurable repository doubles."""
    repository = FakeSessionRepository(**kwargs)
    return Service(
        repository, cache_repository, inactivity_minutes=inactivity_minutes
    ), repository


@pytest.fixture
def recorded_metrics():
    """Capture SDK run metrics for the duration of the test."""
    metrics = []
    set_aeko_metrics_sink(metrics.append)
    yield metrics
    set_aeko_metrics_sink(None)


def failing_messengers(error):
    """Build messengers that raise the configured exception."""
    error.aeko_metrics = StubMetrics(
        error_description=f"{type(error).__name__}: {error}"
    )
    return StubMessengerFactory(error=error)


def send(
    service,
    id_session=ID_SESSION,
    input="hi",
    id_user=ID_USER,
    messengers=None,
    sessions=None,
    users=None,
):
    """Send or capture the request messages used by the test."""
    result = service.send_message(
        id_session,
        input,
        id_user,
        messengers or StubMessengerFactory(),
        sessions or StubSessionFactory(),
        users or StubUserRepository(),
    )
    return result.message


def test_service_implements_the_service_interface():
    """Verify that service implements the service interface."""
    assert issubclass(Service, IService)
    assert Service.__abstractmethods__ == frozenset()


def test_send_message_signature_matches_the_interface():
    """Verify that send message signature matches the interface."""
    interface = inspect.signature(IService.send_message).parameters
    implementation = inspect.signature(Service.send_message).parameters

    assert list(interface) == list(implementation)
    assert "aeko_messenger_factory" in interface
    assert "aeko_session_factory" in interface
    assert "user_repository" in interface


def test_get_user_sessions_delegates_to_the_repository():
    """Verify that get user sessions delegates to the repository."""
    service, _ = build_service()

    sessions = service.get_user_sessions(ID_USER)

    assert [session.id for session in sessions] == [ID_SESSION]


def test_get_user_sessions_propagates_value_error():
    """Verify that get user sessions propagates value error."""
    service, _ = build_service(error=ValueError("No sessions found."))

    with pytest.raises(ValueError, match="No sessions found."):
        service.get_user_sessions(ID_USER)


def test_get_user_sessions_wraps_unexpected_errors():
    """Verify that get user sessions wraps unexpected errors."""
    service, _ = build_service(error=OSError("mongo down"))

    with pytest.raises(RuntimeError, match="mongo down"):
        service.get_user_sessions(ID_USER)


def test_get_session_messages_delegates_to_the_repository():
    """Verify that get session messages delegates to the repository."""
    service, _ = build_service()

    assert service.get_session_messages(ID_SESSION) == []


def test_get_session_messages_propagates_value_error():
    """Verify that get session messages propagates value error."""
    service, _ = build_service(error=ValueError("Invalid session."))

    with pytest.raises(ValueError, match="Invalid session."):
        service.get_session_messages(ID_SESSION)


def test_get_session_messages_wraps_unexpected_errors():
    """Verify that get session messages wraps unexpected errors."""
    service, _ = build_service(error=OSError("mongo down"))

    with pytest.raises(RuntimeError, match="mongo down"):
        service.get_session_messages(ID_SESSION)


def test_metric_company_requires_positive_integer():
    """Verify that SDK metrics require a positive id_external_company."""
    with pytest.raises(ValueError, match="id_external_company"):
        _metric_company(
            User(
                id=ID_USER,
                id_external_user=12345,
                role="analyst",
                usecase="report_generation",
                id_external_company=None,
            )
        )


def test_send_message_requires_id_external_company():
    """Verify that chat is rejected when the user has no company snapshot."""
    service, _ = build_service()
    users = StubUserRepository(
        User(
            id=ID_USER,
            id_external_user=12345,
            role="analyst",
            usecase="report_generation",
            id_external_company=None,
        )
    )

    with pytest.raises(ValueError, match="id_external_company"):
        send(service, users=users)


def test_send_message_returns_the_exchange():
    """Verify that send message returns the exchange."""
    service, _ = build_service()

    result = service.send_message(
        ID_SESSION,
        "What is scope 3?",
        ID_USER,
        StubMessengerFactory(),
        StubSessionFactory(),
        StubUserRepository(),
    )

    assert isinstance(result.message, Message)
    assert result.message.input == "What is scope 3?"
    assert result.message.output == "echo: What is scope 3?"
    assert result.session.id == ID_SESSION


def test_send_message_reads_the_turn_out_of_the_response_message():
    """Verify that send message reads the turn out of the response message."""
    messengers = StubMessengerFactory(turn=StubTurn(input="hi", output="ho"))
    service, _ = build_service()

    message = send(service, messengers=messengers)

    assert (message.input, message.output) == ("hi", "ho")


def test_a_stored_turn_is_only_what_it_said_and_when():
    """Verify that a stored turn is only what it said and when."""
    message = send(build_service()[0])

    assert set(vars(message)) == {"input", "output", "submitted_at"}


def test_send_message_stamps_the_exchange_when_the_turn_carries_no_time():
    """Verify that send message stamps the exchange when the turn carries no time."""
    service, _ = build_service()

    assert isinstance(send(service).submitted_at, datetime)


def test_send_message_keeps_the_submission_time_the_sdk_produced():
    """Verify that send message keeps the submission time the sdk produced."""
    messengers = StubMessengerFactory(
        turn=StubTurn(input="hi", output="ho", submitted_at=SUBMITTED_AT)
    )
    service, _ = build_service()

    assert send(service, messengers=messengers).submitted_at == SUBMITTED_AT


def test_send_message_persists_the_exchange():
    """Verify that send message persists the exchange."""
    service, repository = build_service()

    message = send(service)

    assert repository.saved == [(ID_SESSION, message)]


def test_send_message_builds_the_messenger_for_the_asking_user():
    """Verify that send message builds the messenger for the asking user."""
    messengers = StubMessengerFactory()
    service, _ = build_service()

    send(service, messengers=messengers)

    assert messengers.last.user is USER


def test_send_message_hands_over_the_session_and_the_text():
    """Verify that send message hands over the session and the text."""
    messengers, sessions = StubMessengerFactory(), StubSessionFactory()
    service, _ = build_service()

    send(service, input="What is scope 3?", messengers=messengers, sessions=sessions)

    text, document, _ = messengers.last.sent[0]
    assert text == "What is scope 3?"
    assert document is sessions.last
    assert document.id == ID_SESSION


def test_send_message_rehydrates_the_conversation_into_the_session():
    """Verify that send message rehydrates the conversation into the session."""
    stored = Message(
        input="Summarize this session.",
        output="Here is the summary.",
        submitted_at=SUBMITTED_AT,
    )
    sessions = StubSessionFactory()
    service, _ = build_service(messages={ID_SESSION: [stored]})

    send(service, sessions=sessions)

    assert [turn.input for turn in sessions.last.messages] == [
        "Summarize this session."
    ]


def test_send_message_prefers_cached_messages_over_mongo():
    """Verify that send message prefers cached messages over mongo."""
    mongo_turn = Message(input="mongo", output="stored", submitted_at=SUBMITTED_AT)
    cached_turn = Message(input="redis", output="window", submitted_at=SUBMITTED_AT)
    cache = StubCacheRepository(
        windows={ID_SESSION: SessionWindow(ID_USER, [cached_turn])}
    )
    sessions = StubSessionFactory()
    service, repository = build_service(
        cache_repository=cache,
        messages={ID_SESSION: [mongo_turn]},
    )

    send(service, sessions=sessions)

    assert [turn.input for turn in sessions.last.messages] == ["redis"]
    assert repository.message_lookups == []


def test_send_message_falls_back_to_mongo_when_the_cache_is_empty():
    """Verify that send message falls back to mongo when the cache is empty."""
    mongo_turn = Message(input="mongo", output="stored", submitted_at=SUBMITTED_AT)
    cache = StubCacheRepository(windows={ID_SESSION: SessionWindow(ID_USER, [])})
    sessions = StubSessionFactory()
    service, repository = build_service(
        cache_repository=cache,
        messages={ID_SESSION: [mongo_turn]},
    )

    send(service, sessions=sessions)

    assert [turn.input for turn in sessions.last.messages] == ["mongo"]
    assert repository.message_lookups == [ID_SESSION]


def test_send_message_falls_back_to_mongo_when_the_cache_has_no_window():
    """Verify that send message falls back to mongo when the cache has no window."""
    mongo_turn = Message(input="mongo", output="stored", submitted_at=SUBMITTED_AT)
    cache = StubCacheRepository()
    sessions = StubSessionFactory()
    service, _ = build_service(
        cache_repository=cache,
        messages={ID_SESSION: [mongo_turn]},
    )

    send(service, sessions=sessions)

    assert [turn.input for turn in sessions.last.messages] == ["mongo"]


def test_send_message_refreshes_the_cached_window_after_the_turn():
    """Verify that send message refreshes the cached window after the turn."""
    cached_turn = Message(input="redis", output="window", submitted_at=SUBMITTED_AT)
    cache = StubCacheRepository(
        windows={ID_SESSION: SessionWindow(ID_USER, [cached_turn])}
    )
    service, _ = build_service(cache_repository=cache, inactivity_minutes=20)

    message = send(service)

    window = cache.windows[ID_SESSION]
    assert [turn.input for turn in window.messages] == ["redis", message.input]
    assert cache.activity[ID_SESSION] == 1200


def test_send_message_does_not_refresh_the_cache_when_the_turn_is_rejected():
    """Verify that send message does not refresh the cache when the turn is rejected."""
    cache = StubCacheRepository()
    service, _ = build_service(cache_repository=cache)

    with pytest.raises(GuardrailRejectedError):
        send(service, messengers=StubMessengerFactory(approved=False))

    assert cache.windows == {}
    assert cache.activity == {}


def test_send_message_hands_over_only_the_memories_that_are_still_valid():
    """Verify that send message hands over only the memories that are still valid."""
    valid = UserMemory(
        id="m1", id_user=ID_USER, field="preferred_language", description="pt-BR"
    )
    expiring = UserMemory(
        id="m2",
        id_user=ID_USER,
        field="soon",
        description="still valid",
        expires_at=datetime.utcnow() + timedelta(days=1),
    )
    expired = UserMemory(
        id="m3",
        id_user=ID_USER,
        field="stale",
        description="gone",
        expires_at=datetime.utcnow() - timedelta(seconds=1),
    )
    messengers = StubMessengerFactory()
    service, _ = build_service()

    send(
        service,
        messengers=messengers,
        users=StubUserRepository(memories=[valid, expiring, expired]),
    )

    assert [memory.field for memory in messengers.last.memories] == [
        "preferred_language",
        "soon",
    ]


def test_send_message_rejects_an_unknown_user():
    """Verify that send message rejects an unknown user."""
    service, _ = build_service()

    with pytest.raises(ValueError, match="does not exist"):
        send(service, users=StubUserRepository(user=None))


def test_send_message_creates_a_session_when_none_is_given():
    """Verify that send message creates a session when none is given."""
    messengers, sessions = StubMessengerFactory(), StubSessionFactory()
    service, repository = build_service()
    users = StubUserRepository()

    send(service, id_session="", messengers=messengers, sessions=sessions, users=users)

    assert repository.created_for == [(ID_USER, users)]
    assert sessions.last.id == "session-2"


def test_send_message_names_a_brand_new_session_after_its_first_message():
    """Verify that send message names a brand new session after its first message."""
    service, repository = build_service()

    result = service.send_message(
        "",
        "How do I cut boiler emissions?",
        ID_USER,
        StubMessengerFactory(),
        StubSessionFactory(),
        StubUserRepository(),
    )

    assert repository.names == {"session-2": "How do I cut boiler emissions?"}
    assert result.session.id == "session-2"
    assert result.session.name == "How do I cut boiler emissions?"


def test_send_message_shortens_a_long_first_message_into_the_session_name():
    """Verify that send message shortens a long first message into the session name."""
    service, repository = build_service()

    send(service, id_session="", input="scope 1 " * 40)

    name = repository.names["session-2"]
    assert len(name) <= 63
    assert name.endswith("...")


def test_send_message_does_not_rename_an_existing_session():
    """Verify that send message does not rename an existing session."""
    service, repository = build_service()

    send(service)

    assert repository.names == {}


def test_send_message_deletes_a_brand_new_session_when_its_first_message_fails():
    """Verify that a failed first message leaves no nameless session behind."""
    service, repository = build_service()

    with pytest.raises(RuntimeError, match="sdk down"):
        send(service, id_session="", messengers=failing_messengers(OSError("sdk down")))

    assert "session-2" not in repository.sessions
    assert repository.names == {}


def test_send_message_keeps_an_existing_session_when_a_message_fails():
    """Verify that a failed message never deletes a session that already existed."""
    service, repository = build_service()

    with pytest.raises(RuntimeError, match="sdk down"):
        send(service, messengers=failing_messengers(OSError("sdk down")))

    assert ID_SESSION in repository.sessions


def test_send_message_raises_when_no_reviewer_approved_a_draft():
    """Verify that send message raises when no reviewer approved a draft."""
    service, _ = build_service()

    with pytest.raises(GuardrailRejectedError):
        send(service, messengers=StubMessengerFactory(approved=False))


def test_send_message_persists_nothing_when_no_reviewer_approved_a_draft():
    """Verify that send message persists nothing when no reviewer approved a draft."""
    service, repository = build_service()

    with pytest.raises(GuardrailRejectedError):
        send(service, messengers=StubMessengerFactory(approved=False))

    assert repository.saved == []


def test_send_message_rejects_a_session_that_reached_the_message_limit():
    """Verify that send message rejects a session that reached the message limit."""
    service, _ = build_service(messages_count=50)

    with pytest.raises(ValueError, match="maximum number of messages"):
        send(service)


def test_send_message_accepts_a_session_below_the_message_limit():
    """Verify that send message accepts a session below the message limit."""
    service, repository = build_service(messages_count=49)

    send(service)

    assert len(repository.saved) == 1


def test_send_message_rejects_a_session_owned_by_another_user():
    """Verify that send message rejects a session owned by another user."""
    service, _ = build_service()

    with pytest.raises(ValueError, match="not allowed"):
        send(
            service,
            id_user="someone-else",
            users=StubUserRepository(
                user=User(
                    id="someone-else", id_external_user=999, role="r", usecase="u"
                )
            ),
        )


def test_send_message_propagates_a_value_error_from_the_repository():
    """Verify that send message propagates a value error from the repository."""
    service, _ = build_service(error=ValueError("User with id_user u1 does not exist."))

    with pytest.raises(ValueError, match="does not exist"):
        send(service, id_session="")


def test_send_message_wraps_unexpected_errors():
    """Verify that send message wraps unexpected errors."""
    service, _ = build_service(error=OSError("mongo down"))

    with pytest.raises(RuntimeError, match="mongo down"):
        send(service)


def test_send_message_wraps_an_sdk_failure():
    """Verify that send message wraps an sdk failure."""
    service, _ = build_service()

    with pytest.raises(RuntimeError, match="gemini down"):
        send(service, messengers=StubMessengerFactory(error=OSError("gemini down")))


def test_validation_returns_true_for_an_allowed_user():
    """Verify that validation returns true for an allowed user."""
    service, _ = build_service()

    assert service._validate_session_and_user_allowance(ID_SESSION, ID_USER) is True


def test_validation_wraps_unexpected_errors():
    """Verify that validation wraps unexpected errors."""
    service, _ = build_service(error=OSError("mongo down"))

    with pytest.raises(RuntimeError, match="mongo down"):
        service._validate_session_and_user_allowance(ID_SESSION, ID_USER)


def test_the_sdk_is_handed_the_identifier_the_request_is_tracked_under():
    """Verify that the sdk is handed the identifier the request is tracked under."""
    messengers = StubMessengerFactory()
    service, _ = build_service()
    token = bind_id_request("65a8b3d6c0f8e1d7f4b2c0aa")

    try:
        send(service, messengers=messengers)
    finally:
        unbind_id_request(token)

    _, _, id_request = messengers.last.sent[0]
    assert id_request == "65a8b3d6c0f8e1d7f4b2c0aa"


def test_a_call_made_outside_a_request_still_reaches_the_sdk():
    """Verify that a call made outside a request still reaches the sdk."""
    messengers = StubMessengerFactory()
    service, _ = build_service()

    send(service, messengers=messengers)

    assert messengers.last.sent[0][2] == ""


def test_an_answered_turn_records_what_the_run_cost(recorded_metrics):
    """Verify that an answered turn records what the run cost."""
    service, _ = build_service()
    token = bind_id_request("65a8b3d6c0f8e1d7f4b2c0aa")

    try:
        send(service)
    finally:
        unbind_id_request(token)

    assert [metrics.id_request for metrics in recorded_metrics] == [
        "65a8b3d6c0f8e1d7f4b2c0aa"
    ]
    assert recorded_metrics[0].error_description is None


def test_an_answered_turn_records_the_user_company():
    """Verify that an answered turn records the user company."""
    from internal.shared.event_tracking import (
        current_metric_id_external_company,
        current_metric_id_external_user,
    )

    seen = []

    def sink(metrics):
        """Capture the owner bound while the sink runs."""
        seen.append(
            (current_metric_id_external_user(), current_metric_id_external_company())
        )

    set_aeko_metrics_sink(sink)
    try:
        send(build_service()[0])
    finally:
        set_aeko_metrics_sink(None)

    assert seen == [(12345, 90)]


def test_a_turn_no_reviewer_approved_is_recorded_as_the_failure_it_was(
    recorded_metrics,
):
    """Verify that a turn no reviewer approved is recorded as the failure it was."""
    service, repository = build_service()

    with pytest.raises(GuardrailRejectedError):
        send(service, messengers=StubMessengerFactory(approved=False))

    assert len(recorded_metrics) == 1
    assert recorded_metrics[0].error_description == REVIEW_FAILURE
    assert repository.saved == []


def test_a_run_that_raised_records_the_tracking_it_carried_out(recorded_metrics):
    """Verify that a run that raised records the tracking it carried out."""
    service, _ = build_service()

    with pytest.raises(RuntimeError, match="gemini down"):
        send(service, messengers=failing_messengers(OSError("gemini down")))

    assert [metrics.error_description for metrics in recorded_metrics] == [
        "OSError: gemini down"
    ]


def test_a_failure_carrying_no_tracking_records_nothing(recorded_metrics):
    """Verify that a failure carrying no tracking records nothing."""
    service, _ = build_service()

    with pytest.raises(RuntimeError, match="gemini down"):
        send(service, messengers=StubMessengerFactory(error=OSError("gemini down")))

    assert recorded_metrics == []


def test_a_recording_that_fails_never_takes_the_exchange_down():
    """Verify that a recording that fails never takes the exchange down."""

    def explode(metrics):
        """Raise the configured failure to exercise error handling."""
        raise RuntimeError("mongo is down")

    service, _ = build_service()
    set_aeko_metrics_sink(explode)

    try:
        message = send(service, input="What is scope 3?")
    finally:
        set_aeko_metrics_sink(None)

    assert message.output == "echo: What is scope 3?"
