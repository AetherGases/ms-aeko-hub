"""Verify session routes behavior and error handling."""

import asyncio
from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from internal.http import session_handlers
from tests.ms_auth_doubles import ms_auth_principal, override_ms_auth

SEND_BODY = {
    "id_session": "s1",
    "input": "hi",
    "id_external_user": 12345,
    "id_external_company": 90,
}
from session.entity import Message, Session
from user.entity import User
from session.session import GuardrailRejectedError

SESSIONS_ROUTE = "/ai/sessions/user/{id_user}"
MESSAGES_ROUTE = "/ai/session/{id_session}/messages"
SEND_ROUTE = "/ai/user/session/message"

SUBMITTED_AT = datetime(2026, 7, 26, 14, 30, 0)


class StubSessionService:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    def _run(self, **call):
        self.calls.append(call)
        if self.error is not None:
            raise self.error
        return self.result

    def get_user_sessions(self, id_user):
        """Retrieve the sessions belonging to a user."""
        return self._run(id_user=id_user)

    def get_session_messages(self, id_session):
        """Retrieve the stored messages for a session."""
        return self._run(id_session=id_session)

    def send_message(self, id_session, input, id_user, aeko_messenger_factory,
                     aeko_session_factory, user_repository):
        """Record the conversation call and return or raise its scripted result."""
        return self._run(
            id_session=id_session,
            input=input,
            id_user=id_user,
            aeko_messenger_factory=aeko_messenger_factory,
            aeko_session_factory=aeko_session_factory,
            user_repository=user_repository,
        )

    def _validate_session_and_user_allowance(self, id_session, id_user):
        raise NotImplementedError


class StubUserRepository:
    """Return scripted users for authorization checks in route tests."""

    def __init__(self, db=None, users_by_id=None):
        default = User(id="u1", id_external_user=12345, role="analyst", usecase="chat")
        self.users_by_id = users_by_id or {"u1": default}

    def get_user_by_id(self, id_user):
        """Return the scripted user for an internal id, or None when unknown."""
        return self.users_by_id.get(id_user)


class StubSessionRepository:
    """Return scripted sessions for authorization checks in route tests."""

    def __init__(self, sessions_by_id=None):
        default = Session(id="s1", id_user="u1", name="Weekly emissions review", messages=[])
        self.sessions_by_id = sessions_by_id or {"s1": default}

    def get_session(self, id_session):
        """Return the scripted session or raise when the id is unknown."""
        session = self.sessions_by_id.get(id_session)
        if session is None:
            raise ValueError(f"No session found with id_session {id_session}.")
        return session


def build_client(service=None, db="fake-db", factories=True, user_repository=None, session_repository=None):
    """Build a test client or client double with the supplied dependencies."""
    app = FastAPI()
    app.include_router(session_handlers.router)
    app.state.db = db
    override_ms_auth(app)
    if factories:
        app.state._state["aeko_messenger_factory"] = MESSENGER_FACTORY
        app.state._state["aeko_session_factory"] = SESSION_FACTORY
    if service is not None:
        app.dependency_overrides[session_handlers.get_session_service] = lambda: service
    user_repo = user_repository or StubUserRepository()
    session_repo = session_repository or StubSessionRepository()
    app.dependency_overrides[session_handlers.get_user_repository] = lambda: user_repo
    app.dependency_overrides[session_handlers.get_session_repository] = lambda: session_repo
    return TestClient(app)


def MESSENGER_FACTORY(user, memories):
    """Provide the messenger factory used by the route test."""
    raise AssertionError("the stub service never runs the SDK")


def SESSION_FACTORY(session):
    """Provide the session factory used by the route test."""
    raise AssertionError("the stub service never runs the SDK")


def make_message(input="Summarize this session.", output="Here is the summary."):
    """Build a message fixture for session responses."""
    return Message(input=input, output=output, submitted_at=SUBMITTED_AT)


def test_get_user_sessions_returns_sessions():
    """Verify that get user sessions returns sessions."""
    service = StubSessionService(
        result=[
            Session(id="65a8b3d6c0f8e1d7f4b2c001", id_user="u1", name="Weekly emissions review", messages=[]),
            Session(id="65a8b3d6c0f8e1d7f4b2c002", id_user="u1", name="Scope 3 questions", messages=[]),
        ]
    )
    response = build_client(service).get(SESSIONS_ROUTE.format(id_user="u1"))

    assert response.status_code == 200
    assert response.json() == [
        {"id": "65a8b3d6c0f8e1d7f4b2c001", "name": "Weekly emissions review"},
        {"id": "65a8b3d6c0f8e1d7f4b2c002", "name": "Scope 3 questions"},
    ]
    assert service.calls == [{"id_user": "u1"}]


def test_get_user_sessions_returns_empty_list():
    """Verify that get user sessions returns empty list."""
    response = build_client(StubSessionService(result=[])).get(SESSIONS_ROUTE.format(id_user="u1"))

    assert response.status_code == 200
    assert response.json() == []


def test_get_user_sessions_maps_value_error_to_404():
    """Verify that get user sessions maps value error to 404."""
    service = StubSessionService(error=ValueError("No sessions found."))
    response = build_client(service).get(SESSIONS_ROUTE.format(id_user="u1"))

    assert response.status_code == 404
    assert response.json()["detail"] == "No sessions found."


def test_get_user_sessions_returns_404_when_internal_user_is_unknown():
    """Verify that get user sessions returns 404 when the internal user does not exist."""
    response = build_client(StubSessionService(result=[])).get(SESSIONS_ROUTE.format(id_user="ghost"))

    assert response.status_code == 404
    assert response.json()["detail"] == "User not found."


def test_get_user_sessions_maps_unexpected_error_to_500():
    """Verify that get user sessions maps unexpected error to 500."""
    service = StubSessionService(error=RuntimeError("boom"))
    response = build_client(service).get(SESSIONS_ROUTE.format(id_user="u1"))

    assert response.status_code == 500
    assert "boom" in response.json()["detail"]


def test_get_user_sessions_returns_503_when_database_is_not_initialized():
    """Verify that get user sessions returns 503 when database is not initialized."""
    response = build_client(service=None, db=None).get(SESSIONS_ROUTE.format(id_user="u1"))

    assert response.status_code == 503
    assert response.json()["detail"] == "Database is not initialized"


def test_get_session_messages_returns_messages():
    """Verify that get session messages returns messages."""
    service = StubSessionService(result=[make_message()])
    response = build_client(service).get(MESSAGES_ROUTE.format(id_session="s1"))

    assert response.status_code == 200
    assert response.json() == [
        {
            "input_message": "Summarize this session.",
            "output_message": "Here is the summary.",
            "submitted_at": SUBMITTED_AT.isoformat(),
        }
    ]
    assert service.calls == [{"id_session": "s1"}]


def test_get_session_messages_maps_value_error_to_400():
    """Verify that get session messages maps value error to 400."""
    service = StubSessionService(error=ValueError("Invalid session."))

    class InvalidSessionRepository(StubSessionRepository):
        def get_session(self, id_session):
            """Raise the scripted validation error for authorization tests."""
            raise ValueError("Invalid session.")

    response = build_client(service, session_repository=InvalidSessionRepository()).get(
        MESSAGES_ROUTE.format(id_session="bad")
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid session."


def test_get_session_messages_maps_unexpected_error_to_500():
    """Verify that get session messages maps unexpected error to 500."""
    service = StubSessionService(error=RuntimeError("boom"))
    response = build_client(service).get(MESSAGES_ROUTE.format(id_session="s1"))

    assert response.status_code == 500
    assert "boom" in response.json()["detail"]


class StubUserService:
    """Return scripted users from get_mongo_user_or_create in route tests."""

    create_calls = []

    def __init__(self, repository=None):
        self.repository = repository

    def get_mongo_user_or_create(
        self,
        id_external_user,
        role,
        usecase,
        *,
        id_external_company=None,
    ):
        """Record provisioning and return the scripted Mongo user."""
        StubUserService.create_calls.append(
            {
                "id_external_user": id_external_user,
                "role": role,
                "usecase": usecase,
                "id_external_company": id_external_company,
            }
        )
        return User(
            id="u1",
            id_external_user=id_external_user,
            role=role,
            usecase=usecase,
            id_external_company=id_external_company,
        )


@pytest.fixture
def patched_user_repository(monkeypatch):
    """Replace the route user repository and service with test doubles."""
    monkeypatch.setattr(session_handlers, "UserRepository", StubUserRepository)
    monkeypatch.setattr(session_handlers, "UserService", StubUserService)
    return StubUserRepository


def test_send_message_returns_the_exchange(patched_user_repository):
    """Verify that send message returns the exchange."""
    service = StubSessionService(result=make_message())

    response = build_client(service).post(
        SEND_ROUTE,
        json={**SEND_BODY, "input": "Summarize this session."},
    )

    assert response.status_code == 200
    assert response.json() == {
        "input_message": "Summarize this session.",
        "output_message": "Here is the summary.",
        "submitted_at": SUBMITTED_AT.isoformat(),
    }


def test_send_message_injects_both_sdk_factories_from_app_state(patched_user_repository):
    """Verify that send message injects both sdk factories from app state."""
    service = StubSessionService(result=make_message())

    build_client(service).post(
        SEND_ROUTE,
        json={**SEND_BODY, "id_session": "", "input": "hi"},
    )

    call = service.calls[0]
    assert call["aeko_messenger_factory"] is MESSENGER_FACTORY
    assert call["aeko_session_factory"] is SESSION_FACTORY
    assert call["id_session"] == ""
    assert call["id_user"] == "u1"
    assert isinstance(call["user_repository"], StubUserRepository)


def test_send_message_defaults_optional_session_and_input(patched_user_repository):
    """Verify that send message defaults optional session and input fields."""
    service = StubSessionService(result=make_message())

    build_client(service).post(
        SEND_ROUTE,
        json={"id_external_user": 12345, "id_external_company": 90},
    )

    assert service.calls[0]["input"] == ""
    assert service.calls[0]["id_session"] is None


def test_send_message_ignores_id_user_in_the_body(patched_user_repository):
    """Verify that send message resolves identity from external ids, not id_user."""
    service = StubSessionService(result=make_message())

    build_client(service).post(
        SEND_ROUTE,
        json={**SEND_BODY, "id_user": "attacker-internal-id"},
    )

    assert service.calls[0]["id_user"] == "u1"


def test_send_message_returns_500_when_the_sdk_is_not_initialized():
    """Verify that send message returns 500 when the sdk is not initialized."""
    service = StubSessionService(result=make_message())

    response = build_client(service, factories=False).post(SEND_ROUTE, json=SEND_BODY)

    assert response.status_code == 500
    assert response.json()["detail"] == "Aeko SDK is not initialized"


def test_send_message_maps_value_error_to_400(patched_user_repository):
    """Verify that send message maps value error to 400."""
    service = StubSessionService(error=ValueError("Session limit reached."))

    response = build_client(service).post(SEND_ROUTE, json=SEND_BODY)

    assert response.status_code == 400
    assert response.json()["detail"] == "Session limit reached."


def test_send_message_maps_a_rejected_answer_to_502(patched_user_repository):
    """Verify that send message maps a rejected answer to 502."""
    service = StubSessionService(
        error=GuardrailRejectedError("The output guardrail rejected every draft.")
    )

    response = build_client(service).post(SEND_ROUTE, json=SEND_BODY)

    assert response.status_code == 502
    assert response.json()["detail"] == "The output guardrail rejected every draft."


def test_send_message_maps_unexpected_error_to_500(patched_user_repository):
    """Verify that send message maps unexpected error to 500."""
    service = StubSessionService(error=RuntimeError("boom"))

    response = build_client(service).post(SEND_ROUTE, json=SEND_BODY)

    assert response.status_code == 500
    assert "boom" in response.json()["detail"]


def test_send_message_returns_403_when_external_user_differs(patched_user_repository):
    """Verify that send message rejects a body user that does not match the token."""
    StubUserService.create_calls = []
    service = StubSessionService(result=make_message())
    app = FastAPI()
    app.include_router(session_handlers.router)
    app.state.db = "fake-db"
    app.state._state["aeko_messenger_factory"] = MESSENGER_FACTORY
    app.state._state["aeko_session_factory"] = SESSION_FACTORY
    override_ms_auth(app, ms_auth_principal(id_external_user=12345))
    app.dependency_overrides[session_handlers.get_session_service] = lambda: service
    app.dependency_overrides[session_handlers.get_user_repository] = lambda: StubUserRepository()

    response = TestClient(app).post(
        SEND_ROUTE,
        json={**SEND_BODY, "id_external_user": 99999},
    )

    assert response.status_code == 403
    assert service.calls == []
    assert StubUserService.create_calls == []


def test_send_message_returns_403_when_external_company_differs(patched_user_repository):
    """Verify that send message rejects a body company that does not match the token."""
    StubUserService.create_calls = []
    service = StubSessionService(result=make_message())
    app = FastAPI()
    app.include_router(session_handlers.router)
    app.state.db = "fake-db"
    app.state._state["aeko_messenger_factory"] = MESSENGER_FACTORY
    app.state._state["aeko_session_factory"] = SESSION_FACTORY
    override_ms_auth(app, ms_auth_principal(id_external_company=90))
    app.dependency_overrides[session_handlers.get_session_service] = lambda: service
    app.dependency_overrides[session_handlers.get_user_repository] = lambda: StubUserRepository()

    response = TestClient(app).post(
        SEND_ROUTE,
        json={**SEND_BODY, "id_external_company": 99},
    )

    assert response.status_code == 403
    assert service.calls == []
    assert StubUserService.create_calls == []


def test_send_message_provisions_with_empty_role_and_usecase(patched_user_repository):
    """Verify auto-create passes empty role and usecase to UserService."""
    StubUserService.create_calls = []
    service = StubSessionService(result=make_message())

    response = build_client(service).post(SEND_ROUTE, json=SEND_BODY)

    assert response.status_code == 200
    assert len(StubUserService.create_calls) == 1
    call = StubUserService.create_calls[0]
    assert call["role"] == ""
    assert call["usecase"] == ""
    assert call["id_external_user"] == 12345
    assert call["id_external_company"] == 90


@pytest.mark.parametrize(
    "json_body",
    [
        pytest.param({k: v for k, v in SEND_BODY.items() if k != "id_external_user"}, id="missing_id_external_user"),
        pytest.param({k: v for k, v in SEND_BODY.items() if k != "id_external_company"}, id="missing_id_external_company"),
        pytest.param({**SEND_BODY, "id_external_user": 0}, id="zero_id_external_user"),
        pytest.param({**SEND_BODY, "id_external_company": 0}, id="zero_id_external_company"),
        pytest.param({**SEND_BODY, "id_external_user": -1}, id="negative_id_external_user"),
        pytest.param({**SEND_BODY, "id_external_company": -1}, id="negative_id_external_company"),
        pytest.param({**SEND_BODY, "id_external_user": "not-a-number"}, id="non_numeric_id_external_user"),
        pytest.param({**SEND_BODY, "id_external_company": "not-a-number"}, id="non_numeric_id_external_company"),
    ],
)
def test_send_message_returns_400_and_never_creates_on_invalid_external_ids(
    patched_user_repository, json_body
):
    """Verify invalid external ids return 400 without provisioning or send_message."""
    StubUserService.create_calls = []
    service = StubSessionService(result=make_message())

    response = build_client(service).post(SEND_ROUTE, json=json_body)

    assert response.status_code == 400
    assert "must be a positive integer" in response.json()["detail"]
    assert service.calls == []
    assert StubUserService.create_calls == []


COST_ROUTE = "/ai/sessions/cost"


class StubMetricsService:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    def add_metric(self, metric):
        """Store a metric through the repository and return the stored entity."""
        raise NotImplementedError

    def get_all_metrics(self):
        """Retrieve all stored metrics."""
        raise NotImplementedError

    def company_cost(self, n, id_external_company):
        """Return the scripted company cost or raise the configured error."""
        self.calls.append((n, id_external_company))
        if self.error is not None:
            raise self.error
        return self.result


def build_cost_client(service=None, db="fake-db", id_external_company=90):
    """Build a client for the sessions cost route with a stub metrics service."""
    app = FastAPI()
    app.include_router(session_handlers.router)
    app.state.db = db
    override_ms_auth(app, ms_auth_principal(id_external_company=id_external_company))
    if service is not None:
        app.dependency_overrides[session_handlers.get_aeko_metrics_service] = lambda: service
    return TestClient(app)


def test_the_sessions_cost_route_returns_company_total_and_users():
    """Verify that the sessions cost route returns company total and users."""
    from aeko_metrics.entity import CompanyCost, UserCost

    service = StubMetricsService(
        result=CompanyCost(
            id_external_company=90,
            cost_usd=0.45,
            users=[
                UserCost(id_external_user=1, cost_usd=0.25),
                UserCost(id_external_user=2, cost_usd=0.20),
            ],
        )
    )
    response = build_cost_client(service).get(
        COST_ROUTE, params={"n": 7, "id_external_company": 90}
    )

    assert response.status_code == 200
    assert response.json() == {
        "id_external_company": 90,
        "cost_usd": 0.45,
        "users": [
            {"id_external_user": 1, "cost_usd": 0.25},
            {"id_external_user": 2, "cost_usd": 0.20},
        ],
    }
    assert service.calls == [(7, 90)]


def test_the_sessions_cost_route_maps_value_error_to_400():
    """Verify that the sessions cost route maps value error to 400."""
    service = StubMetricsService(error=ValueError("n must be a positive integer."))
    response = build_cost_client(service).get(
        COST_ROUTE, params={"n": 0, "id_external_company": 90}
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "n must be a positive integer."


def test_the_sessions_cost_route_maps_unexpected_error_to_500():
    """Verify that the sessions cost route maps unexpected error to 500."""
    service = StubMetricsService(error=RuntimeError("boom"))
    response = build_cost_client(service).get(
        COST_ROUTE, params={"n": 7, "id_external_company": 90}
    )

    assert response.status_code == 500
    assert "boom" in response.json()["detail"]


def test_the_sessions_cost_route_returns_503_when_database_is_not_initialized():
    """Verify that the sessions cost route returns 503 when database is not initialized."""
    response = build_cost_client(service=None, db=None).get(
        COST_ROUTE, params={"n": 7, "id_external_company": 90}
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "Database is not initialized"


def test_the_sessions_cost_route_is_registered_on_the_application(api_main):
    """Verify that the sessions cost route is registered on the application."""
    assert "get" in api_main.app.openapi()["paths"].get(COST_ROUTE, {})


def test_the_sessions_cost_route_returns_403_for_another_company():
    """Verify that company cost rejects a company that does not match the token."""
    service = StubMetricsService()
    response = build_cost_client(service, id_external_company=90).get(
        COST_ROUTE, params={"n": 7, "id_external_company": 99}
    )

    assert response.status_code == 403
    assert service.calls == []


def test_get_session_messages_returns_403_when_session_belongs_to_another_user():
    """Verify that session messages return 403 when the session owner does not match the token."""
    other_user = User(id="other", id_external_user=99999, role="analyst", usecase="chat")
    service = StubSessionService(result=[make_message()])
    session_repo = StubSessionRepository(
        sessions_by_id={"s1": Session(id="s1", id_user="other", name="n", messages=[])}
    )
    user_repo = StubUserRepository(users_by_id={"other": other_user})
    response = build_client(service, user_repository=user_repo, session_repository=session_repo).get(
        MESSAGES_ROUTE.format(id_session="s1")
    )

    assert response.status_code == 403
    assert service.calls == []


def test_session_routes_return_401_without_bearer_token():
    """Verify that protected session routes return 401 when Bearer auth is missing."""
    app = FastAPI()
    app.include_router(session_handlers.router)
    app.state.db = "fake-db"
    client = TestClient(app)

    assert client.get(SESSIONS_ROUTE.format(id_user="u1")).status_code == 401
    assert client.get(MESSAGES_ROUTE.format(id_session="s1")).status_code == 401
    assert client.get(COST_ROUTE, params={"n": 7, "id_external_company": 90}).status_code == 401


def test_send_message_runs_the_blocking_sdk_call_off_the_event_loop(patched_user_repository):
    """Verify that send message runs the blocking sdk call off the event loop."""

    class LoopAwareService(StubSessionService):
        def __init__(self):
            """Initialize the service double that records which thread ran send_message."""
            super().__init__(result=make_message())
            self.ran_on_the_event_loop = None

        def send_message(self, *args, **kwargs):
            """Record the conversation call and return or raise its scripted result."""
            try:
                asyncio.get_running_loop()
                self.ran_on_the_event_loop = True
            except RuntimeError:
                self.ran_on_the_event_loop = False
            return super().send_message(*args, **kwargs)

    service = LoopAwareService()
    response = build_client(service).post(SEND_ROUTE, json=SEND_BODY)

    assert response.status_code == 200
    assert service.ran_on_the_event_loop is False
