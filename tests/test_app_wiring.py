"""Verify app wiring behavior and error handling."""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from improvement_plan.database.repository import Repository as ImprovementPlanRepository
from improvement_plan.service import Service as ImprovementPlanService
from internal.http import improvement_plan_handlers, session_handlers, user_handlers
from session.cache.repository import Repository as CacheRepository
from session.database.repository import Repository as SessionRepository
from session.service import Service as SessionService
from tests.conftest import FakeRedis
from tests.mongo_doubles import StubCollection, StubDatabase
from user.database.repository import Repository as UserRepository
from user.service import Service as UserService

REPORT_ROUTE = "/aether-api/v1/ai/report"
SEND_MESSAGE_ROUTE = "/aether-api/v1/ai/user/session/message"
ID_SESSION = "65a8b3d6c0f8e1d7f4b2c001"
ID_USER = "65a8b3d6c0f8e1d7f4b2c010"

USER_DOCUMENT = {
    "_id": ID_USER,
    "id_external_user": 12345,
    "role": "analyst",
    "usecase": "report_generation",
}

SESSION_DOCUMENT = {
    "_id": ID_SESSION,
    "id_user": ID_USER,
    "name": "Weekly emissions review",
}


def request_with(db):
    """Build an application request with the supplied state."""
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db=db)))


def test_report_route_is_registered_on_the_application(api_main):
    """Verify that report route is registered on the application."""
    paths = api_main.app.openapi()["paths"]

    assert "post" in paths.get(REPORT_ROUTE, {})
    assert "get" in paths.get("/aether-api/v1/ai/report/{id_external_inventory}", {})


@pytest.mark.parametrize(
    "path",
    [
        "/aether-api/v1/ai/user/{id_external_user}",
        "/aether-api/v1/ai/sessions/user/{id_user}",
        "/aether-api/v1/ai/session/{id_session}/messages",
        SEND_MESSAGE_ROUTE,
        REPORT_ROUTE,
        "/aether-api/v1/ai/report/{id_external_inventory}",
    ],
)
def test_every_documented_route_is_registered(api_main, path):
    """Verify that every documented route is registered."""
    assert path in api_main.app.openapi()["paths"]


def test_report_route_is_reachable(api_main):
    """Verify that report route is reachable."""
    with TestClient(api_main.app) as client:
        response = client.post(REPORT_ROUTE, json={})

    assert response.status_code != 404


def test_report_route_still_validates_its_body(api_main):
    """Verify that report route still validates its body."""
    with TestClient(api_main.app) as client:
        response = client.post(REPORT_ROUTE, json={"id_external_user": 12345})

    assert response.status_code == 422


def test_lifespan_fails_when_the_database_does_not_answer(api_main, monkeypatch):
    """Verify that lifespan fails when the database does not answer."""
    class UnreachableDatabase:
        def command(self, name):
            """Record a database command and return a simulated success response."""
            raise OSError("no route to host")

    class UnreachableClient:
        def __init__(self, uri=None, *args, **kwargs):
            self.database = UnreachableDatabase()

        def __getitem__(self, name):
            return self.database

        def close(self):
            """Record closure of the simulated resource."""
            pass

    monkeypatch.setattr(api_main, "MongoClient", UnreachableClient)

    with pytest.raises(RuntimeError, match="Failed to connect to MongoDB"):
        with TestClient(api_main.app):
            pass


def test_user_dependency_builds_a_service_backed_by_the_concrete_repository():
    """Verify that user dependency builds a service backed by the concrete repository."""
    service = user_handlers.get_user_service(request_with(StubDatabase()))

    assert isinstance(service, UserService)
    assert isinstance(service.repository, UserRepository)


def test_session_dependency_builds_a_service_backed_by_the_concrete_repository():
    """Verify that session dependency builds a service backed by the concrete repository."""
    service = session_handlers.get_session_service(request_with(StubDatabase()))

    assert isinstance(service, SessionService)
    assert isinstance(service.repository, SessionRepository)
    assert service.cache_repository is None


def test_session_dependency_injects_the_cache_when_redis_is_configured():
    """Verify that session dependency injects the cache when redis is configured."""
    request = request_with(StubDatabase())
    request.app.state.redis = FakeRedis()

    service = session_handlers.get_session_service(request)

    assert isinstance(service.cache_repository, CacheRepository)


def test_report_dependency_builds_a_service_backed_by_the_concrete_repository():
    """Verify that report dependency builds a service backed by the concrete repository."""
    service = improvement_plan_handlers.get_improvement_plan_service(request_with(StubDatabase()))

    assert isinstance(service, ImprovementPlanService)
    assert isinstance(service.repository, ImprovementPlanRepository)


@pytest.mark.parametrize(
    "dependency",
    [
        user_handlers.get_user_service,
        session_handlers.get_session_service,
        improvement_plan_handlers.get_improvement_plan_service,
    ],
)
def test_dependencies_reject_an_uninitialized_database(dependency):
    """Verify that dependencies reject an uninitialized database."""
    with pytest.raises(HTTPException) as exc_info:
        dependency(request_with(None))

    assert exc_info.value.status_code == 503


def build_client(router, database, api_main=None):
    """Build a test client or client double with the supplied dependencies."""
    app = FastAPI()
    app.include_router(router)
    app.state.db = database
    if api_main is not None:
        app.state._state["aeko_messenger_factory"] = api_main.build_messenger
        app.state._state["aeko_session_factory"] = api_main.build_session
    return TestClient(app)


def test_get_user_runs_through_the_concrete_repository():
    """Verify that get user runs through the concrete repository."""
    database = StubDatabase(user=StubCollection(find_one_result=USER_DOCUMENT))

    response = build_client(user_handlers.router, database).get("/aether-api/v1/ai/user/12345")

    assert response.status_code == 200
    assert response.json() == {"id_external_user": 12345, "role": "analyst", "usecase": "report_generation"}


def test_get_user_returns_404_when_the_document_does_not_exist():
    """Verify that get user returns 404 when the document does not exist."""
    database = StubDatabase(user=StubCollection(find_one_result=None))

    response = build_client(user_handlers.router, database).get("/aether-api/v1/ai/user/12345")

    assert response.status_code == 404


def test_get_user_sessions_runs_through_the_concrete_repository():
    """Verify that get user sessions runs through the concrete repository."""
    database = StubDatabase(session=StubCollection(find_result=[SESSION_DOCUMENT]))

    response = build_client(session_handlers.router, database).get(f"/aether-api/v1/ai/sessions/user/{ID_USER}")

    assert response.status_code == 200
    assert response.json() == [{"id": ID_SESSION, "name": "Weekly emissions review"}]


def test_get_session_messages_runs_through_the_concrete_repository():
    """Verify that get session messages runs through the concrete repository."""
    document = {"messages": [{"input": "hi", "output": "ho", "submitted_at": "2026-07-26T14:30:00"}]}
    database = StubDatabase(session=StubCollection(find_one_result=document))

    response = build_client(session_handlers.router, database).get(f"/aether-api/v1/ai/session/{ID_SESSION}/messages")

    assert response.status_code == 200
    assert response.json() == [
        {"input_message": "hi", "output_message": "ho", "submitted_at": "2026-07-26T14:30:00"}
    ]


MESSAGES_DOCUMENT = {
    "messages": [
        {
            "input": "Summarize this session.",
            "output": "Here is the summary.",
            "submitted_at": "2026-07-26T14:30:00",
        }
    ]
}


def session_reads():
    """Record session reads through the application wiring."""
    return [{"messages_count": 0}, SESSION_DOCUMENT, SESSION_DOCUMENT, MESSAGES_DOCUMENT]


def test_send_message_runs_through_the_concrete_repositories(api_main, configured_sdk):
    """Verify that send message runs through the concrete repositories."""
    session_collection = StubCollection(find_one_results=session_reads())
    database = StubDatabase(
        session=session_collection,
        user=StubCollection(find_one_result=USER_DOCUMENT),
        user_memory=StubCollection(find_result=[]),
    )

    response = build_client(session_handlers.router, database, api_main=api_main).post(
        SEND_MESSAGE_ROUTE,
        json={"id_session": ID_SESSION, "input": "What is scope 3?", "id_user": ID_USER},
    )

    assert response.status_code == 200
    assert response.json()["output_message"] == "echo: What is scope 3?"
    assert len(session_collection.call_args("update_one")) == 1


def test_send_message_hands_the_real_dtos_to_the_sdk(api_main, configured_sdk):
    """Verify that send message hands the real dtos to the sdk."""
    database = StubDatabase(
        session=StubCollection(find_one_results=session_reads()),
        user=StubCollection(find_one_result=USER_DOCUMENT),
        user_memory=StubCollection(find_result=[]),
    )

    build_client(session_handlers.router, database, api_main=api_main).post(
        SEND_MESSAGE_ROUTE,
        json={"id_session": ID_SESSION, "input": "What is scope 3?", "id_user": ID_USER},
    )

    messenger = configured_sdk.AekoMessenger.instances[-1]
    _, session, _ = messenger.sent[-1]
    assert isinstance(messenger.user, configured_sdk.AekoUser)
    assert isinstance(session, configured_sdk.AekoSession)
    assert session.id == ID_SESSION
    assert [turn.input for turn in session.messages][0] == "Summarize this session."


def test_send_message_returns_400_when_the_user_does_not_own_the_session(api_main, configured_sdk):
    """Verify that send message returns 400 when the user does not own the session."""
    session_collection = StubCollection(find_one_results=session_reads())
    database = StubDatabase(
        session=session_collection,
        user=StubCollection(find_one_result=USER_DOCUMENT),
        user_memory=StubCollection(find_result=[]),
    )

    response = build_client(session_handlers.router, database, api_main=api_main).post(
        SEND_MESSAGE_ROUTE,
        json={"id_session": ID_SESSION, "input": "hi", "id_user": "someone-else"},
    )

    assert response.status_code == 400


def test_send_message_fails_when_the_sdk_was_never_configured(api_main):
    """Verify that send message fails when the sdk was never configured."""
    database = StubDatabase(
        session=StubCollection(find_one_results=session_reads()),
        user=StubCollection(find_one_result=USER_DOCUMENT),
        user_memory=StubCollection(find_result=[]),
    )

    response = build_client(session_handlers.router, database, api_main=api_main).post(
        SEND_MESSAGE_ROUTE,
        json={"id_session": ID_SESSION, "input": "hi", "id_user": ID_USER},
    )

    assert response.status_code == 500
    assert "not configured" in response.json()["detail"]
