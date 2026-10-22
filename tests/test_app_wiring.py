"""Verify app wiring behavior and error handling."""

import importlib
from pathlib import Path
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
from tests.conftest import FakeMongoClient, FakeRedis
from tests.mongo_doubles import StubCollection, StubDatabase
from user.database.repository import Repository as UserRepository
from tests.ms_auth_doubles import override_ms_auth
from user.service import Service as UserService

REPORT_ROUTE = "/ai/report"
SEND_MESSAGE_ROUTE = "/ai/user/session/message"
SEND_MESSAGE_BODY = {
    "id_session": "65a8b3d6c0f8e1d7f4b2c001",
    "input": "What is scope 3?",
    "id_external_user": 12345,
    "id_external_company": 90,
}
MS_AUTH_HEADERS = {"Authorization": "Bearer ms-access"}
INVENTORY_REPORT_AUTH_HEADERS = {"authentication-key": "test-inventory-report-key"}
ID_SESSION = "65a8b3d6c0f8e1d7f4b2c001"
ID_USER = "65a8b3d6c0f8e1d7f4b2c010"

USER_DOCUMENT = {
    "_id": ID_USER,
    "id_external_user": 12345,
    "role": "analyst",
    "usecase": "report_generation",
    "id_external_company": 90,
}

SESSION_DOCUMENT = {
    "_id": ID_SESSION,
    "id_user": ID_USER,
    "name": "Weekly emissions review",
}


def request_with(db):
    """Build an application request with the supplied state."""
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db=db)))


@pytest.fixture(autouse=True)
def stub_ms_auth_profile_for_full_app(monkeypatch):
    """Stub ms-auth profile resolution when tests hit the full application."""
    from tests.test_profile_api import PROFILE_PAYLOAD

    monkeypatch.setattr(
        "cmd.api.acl.ms_auth_security.get_profile",
        lambda token: PROFILE_PAYLOAD,
    )


def test_mcp_sessions_are_chroma_only(api_main):
    """Verify that mcp sessions are chroma only."""
    assert [session.name for session in api_main.MCP_SESSIONS] == ["chroma"]


def test_report_route_is_registered_on_the_application(api_main):
    """Verify that report route is registered on the application."""
    paths = api_main.app.openapi()["paths"]

    assert "post" in paths.get(REPORT_ROUTE, {})
    assert "get" in paths.get("/ai/report/{id_external_inventory}", {})


def test_swagger_yaml_documents_ms_auth_bearer_on_protected_routes():
    """Verify that swagger.yaml marks protected routes with MsAuthBearer security."""
    swagger = (Path(__file__).resolve().parent.parent / "swagger.yaml").read_text(
        encoding="utf-8"
    )
    assert "securitySchemes:" in swagger
    assert "MsAuthBearer:" in swagger
    assert "scheme: bearer" in swagger
    assert swagger.count("- MsAuthBearer: []") == 6
    assert "operationId: getUserByExternalId" in swagger
    assert "#/components/responses/Unauthorized" in swagger


@pytest.mark.parametrize(
    "path",
    [
        "/ai/user/{id_external_user}",
        "/ai/sessions/cost",
        "/ai/sessions/user/{id_external_user}",
        "/ai/session/{id_session}/messages",
        SEND_MESSAGE_ROUTE,
        "/ai/user/{id_external_user}/inventory-upload/{ticket}/signature",
        "/ai/user/{id_external_user}/inventory-upload/{ticket}/complete",
        REPORT_ROUTE,
        "/ai/report/{id_external_inventory}",
        "/ai/oauth/authorize",
        "/ai/oauth/token",
    ],
)
def test_every_documented_route_is_registered(api_main, path):
    """Verify that every documented route is registered."""
    assert path in api_main.app.openapi()["paths"]


MCP_PREFIX = "/ai/mcp"


def registered_route_paths(app):
    """Collect HTTP paths from the application, including nested included routers."""
    paths = set()

    def walk(routes):
        """Record paths from a route list and walk included routers."""
        for route in routes:
            path = getattr(route, "path", None)
            if path:
                paths.add(path)
            nested = getattr(route, "original_router", None)
            if nested is not None:
                walk(nested.routes)
            elif hasattr(route, "routes"):
                walk(route.routes)

    walk(app.routes)
    return paths


def test_oauth_well_known_routes_are_registered(api_main):
    """Verify that OAuth discovery routes are registered on the application."""
    paths = registered_route_paths(api_main.app)

    assert "/.well-known/oauth-authorization-server" in paths
    assert "/.well-known/oauth-protected-resource" in paths
    assert "/ai/mcp/.well-known/oauth-protected-resource" in paths


def test_chatgpt_mcp_app_is_mounted_at_the_documented_prefix(api_main):
    """Verify that the ChatGPT MCP app is mounted at the documented prefix."""
    mounted = [
        route
        for route in api_main.app.routes
        if getattr(route, "path", None) == MCP_PREFIX
    ]

    assert len(mounted) == 1


def test_chatgpt_mcp_mount_does_not_double_the_inner_path(api_main):
    """Verify that the mounted MCP app serves at its root, not under another /mcp."""
    (mounted,) = [
        route
        for route in api_main.app.routes
        if getattr(route, "path", None) == MCP_PREFIX
    ]
    inner_paths = {getattr(route, "path", None) for route in mounted.app.routes}

    assert "/" in inner_paths
    assert "/mcp" not in inner_paths


def test_lifespan_configures_and_clears_the_chatgpt_tool_bindings(api_main):
    """Verify that lifespan binds inventory and ask_aeko tools and clears them on shutdown."""
    from cmd.api.tools import ask_aeko, inventory_tools

    with TestClient(api_main.app) as client:
        assert client.app.state.ticket_service is not None
        assert client.app.state.oauth is not None
        assert inventory_tools._tickets_service is client.app.state.ticket_service
        assert inventory_tools._create_inventory is not None
        assert inventory_tools._plans_service is not None
        assert ask_aeko._a2a is not None
        assert ask_aeko._aeko_messenger_factory is api_main.build_messenger
        assert ask_aeko._aeko_session_factory is api_main.build_session

    assert inventory_tools._tickets_service is None
    assert inventory_tools._create_inventory is None
    assert inventory_tools._plans_service is None
    assert ask_aeko._a2a is None
    assert ask_aeko._aeko_messenger_factory is None
    assert ask_aeko._aeko_session_factory is None


def test_chatgpt_mcp_accepts_initialize_on_a_public_host(api_main):
    """Verify that the mounted MCP endpoint answers initialize for a non-localhost host."""
    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "chatgpt", "version": "1"},
        },
    }

    with TestClient(api_main.app, base_url="https://aeko.example.com") as client:
        response = client.post(f"{MCP_PREFIX}/", headers=headers, json=body)

    assert response.status_code == 200
    assert response.status_code != 401
    assert "www-authenticate" not in response.headers
    assert "aeko-chatgpt" in response.text


def test_chatgpt_mcp_session_manager_runs_inside_the_lifespan(api_main):
    """Verify that the streamable HTTP session manager is running while the app is up."""
    with TestClient(api_main.app):
        manager = api_main.chatgpt_mcp.session_manager
        assert manager._task_group is not None

    assert manager._task_group is None


def test_report_route_is_reachable(api_main):
    """Verify that report route is reachable."""
    with TestClient(api_main.app) as client:
        response = client.post(
            REPORT_ROUTE, json={}, headers=INVENTORY_REPORT_AUTH_HEADERS
        )

    assert response.status_code != 404


def test_report_route_still_validates_its_body(api_main):
    """Verify that report route still validates its body."""
    with TestClient(api_main.app) as client:
        response = client.post(
            REPORT_ROUTE,
            json={"id_external_user": 12345},
            headers=INVENTORY_REPORT_AUTH_HEADERS,
        )

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
    service = improvement_plan_handlers.get_improvement_plan_service(
        request_with(StubDatabase())
    )

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
    app.state.redis = FakeRedis()
    override_ms_auth(app)
    if api_main is not None:
        app.state._state["aeko_messenger_factory"] = api_main.build_messenger
        app.state._state["aeko_session_factory"] = api_main.build_session
    return TestClient(app)


def test_get_user_runs_through_the_concrete_repository():
    """Verify that get user runs through the concrete repository."""
    database = StubDatabase(user=StubCollection(find_one_result=USER_DOCUMENT))

    response = build_client(user_handlers.router, database).get("/ai/user/12345")

    assert response.status_code == 200
    assert response.json() == {
        "id_external_user": 12345,
        "role": "analyst",
        "usecase": "report_generation",
        "id_external_company": 90,
    }


def test_get_user_returns_404_when_the_document_does_not_exist():
    """Verify that get user returns 404 when the document does not exist."""
    database = StubDatabase(user=StubCollection(find_one_result=None))

    response = build_client(user_handlers.router, database).get("/ai/user/12345")

    assert response.status_code == 404


def test_get_user_sessions_runs_through_the_concrete_repository():
    """Verify that get user sessions runs through the concrete repository."""
    database = StubDatabase(
        session=StubCollection(find_result=[SESSION_DOCUMENT]),
        user=StubCollection(find_one_result=USER_DOCUMENT),
    )

    response = build_client(session_handlers.router, database).get(
        "/ai/sessions/user/12345"
    )

    assert response.status_code == 200
    assert response.json() == [{"id": ID_SESSION, "name": "Weekly emissions review"}]


def test_get_session_messages_runs_through_the_concrete_repository():
    """Verify that get session messages runs through the concrete repository."""
    document = {
        **SESSION_DOCUMENT,
        "messages": [
            {"input": "hi", "output": "ho", "submitted_at": "2026-07-26T14:30:00"}
        ],
    }
    database = StubDatabase(
        user=StubCollection(find_one_result=USER_DOCUMENT),
        session=StubCollection(find_one_results=[SESSION_DOCUMENT, document]),
    )

    response = build_client(session_handlers.router, database).get(
        f"/ai/session/{ID_SESSION}/messages"
    )

    assert response.status_code == 200
    assert response.json() == [
        {
            "input_message": "hi",
            "output_message": "ho",
            "submitted_at": "2026-07-26T14:30:00",
        }
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
    return [
        {"messages_count": 0},
        SESSION_DOCUMENT,
        SESSION_DOCUMENT,
        MESSAGES_DOCUMENT,
    ]


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
        json=SEND_MESSAGE_BODY,
    )

    assert response.status_code == 200
    assert response.json()["output_message"] == "echo: What is scope 3?"
    assert response.json()["id_session"] == ID_SESSION
    assert response.json()["session_name"] == "Weekly emissions review"
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
        json=SEND_MESSAGE_BODY,
    )

    messenger = configured_sdk.AekoMessenger.instances[-1]
    _, session, _ = messenger.sent[-1]
    assert isinstance(messenger.user, configured_sdk.AekoUser)
    assert isinstance(session, configured_sdk.AekoSession)
    assert session.id == ID_SESSION
    assert [turn.input for turn in session.messages][0] == "Summarize this session."


def test_send_message_returns_400_when_the_user_does_not_own_the_session(
    api_main, configured_sdk
):
    """Verify that send message returns 400 when the user does not own the session."""
    foreign_session = {**SESSION_DOCUMENT, "id_user": "someone-else"}
    session_collection = StubCollection(
        find_one_results=[
            {"messages_count": 0},
            foreign_session,
            foreign_session,
            MESSAGES_DOCUMENT,
        ]
    )
    database = StubDatabase(
        session=session_collection,
        user=StubCollection(find_one_result=USER_DOCUMENT),
        user_memory=StubCollection(find_result=[]),
    )

    response = build_client(session_handlers.router, database, api_main=api_main).post(
        SEND_MESSAGE_ROUTE,
        json={**SEND_MESSAGE_BODY, "input": "hi"},
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
        json={**SEND_MESSAGE_BODY, "input": "hi"},
    )

    assert response.status_code == 500
    assert response.json()["detail"] == "Unexpected server error."
    assert "not configured" not in response.text


def test_send_message_updates_company_on_an_existing_mongo_user(
    api_main, configured_sdk
):
    """Verify that send message persists the principal company on an existing Mongo user."""
    existing = {**USER_DOCUMENT, "id_external_company": 80}
    user_collection = StubCollection(find_one_result=existing)
    database = StubDatabase(
        session=StubCollection(find_one_results=session_reads()),
        user=user_collection,
        user_memory=StubCollection(find_result=[]),
    )

    response = build_client(session_handlers.router, database, api_main=api_main).post(
        SEND_MESSAGE_ROUTE,
        json=SEND_MESSAGE_BODY,
    )

    assert response.status_code == 200
    updates = user_collection.call_args("update_one")
    assert any(
        update.get("$set", {}).get("id_external_company") == 90
        for _query, update in updates
    )


def test_docs_return_404_when_env_is_missing(api_main):
    """Verify that missing ENV does not serve OpenAPI docs."""
    assert api_main.app.docs_url is None
    assert api_main.app.redoc_url is None
    assert api_main.app.openapi_url is None
    with TestClient(api_main.app) as client:
        assert client.get("/docs").status_code == 404
        assert client.get("/redoc").status_code == 404
        assert client.get("/openapi.json").status_code == 404


def test_docs_return_404_when_env_is_production(api_main, monkeypatch):
    """Verify that ENV=production does not serve /docs."""
    monkeypatch.setenv("ENV", "production")
    module = importlib.reload(api_main)
    monkeypatch.setattr(module, "MongoClient", FakeMongoClient)
    monkeypatch.setattr(module, "Redis", FakeRedis)
    assert module.app.docs_url is None
    assert module.app.redoc_url is None
    assert module.app.openapi_url is None
    with TestClient(module.app) as client:
        assert client.get("/docs").status_code == 404
        assert client.get("/redoc").status_code == 404
        assert client.get("/openapi.json").status_code == 404


def test_docs_are_enabled_when_env_is_development(api_main, monkeypatch):
    """Verify that ENV=development serves OpenAPI docs regardless of case."""
    monkeypatch.setenv("ENV", "Development")
    module = importlib.reload(api_main)
    monkeypatch.setattr(module, "MongoClient", FakeMongoClient)
    monkeypatch.setattr(module, "Redis", FakeRedis)
    assert module.app.docs_url == "/docs"
    assert module.app.redoc_url == "/redoc"
    assert module.app.openapi_url == "/openapi.json"
    with TestClient(module.app) as client:
        assert client.get("/docs").status_code == 200
        assert client.get("/redoc").status_code == 200
        assert client.get("/openapi.json").status_code == 200
