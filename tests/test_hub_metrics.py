"""Verify hub metrics behavior and error handling."""

import asyncio
import re
from datetime import datetime
from types import SimpleNamespace

import pytest
from bson import ObjectId
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hub_metrics.database import query as q
from hub_metrics.database.repository import Repository, metric_from_data
from hub_metrics.entity import Metric
from hub_metrics.hub_metrics import IRepository, IService
from hub_metrics.service import Service
from internal.shared import event_tracking
from internal.shared.event_tracking import (
    CRASHED_STATUS,
    REQUEST_ID_HEADER,
    UNKNOWN_ENDPOINT,
    Event,
    endpoint_of,
    new_id_request,
    origin_of,
    record_event,
    set_event_sink,
)
from internal.shared.logger import Module
from internal.shared.operation import operation
from internal.shared.request_log import RequestLogMiddleware
from tests.mongo_doubles import StubCollection, StubDatabase

ROUTE = "/ai/hub-metrics"

CREATED_AT = datetime(2026, 3, 10, 12, 0, 0)

HEADER = re.compile(r"^\[aeko-hub\] \[request\] \[[^\]]+\] (?P<description>.*)$")
LINE = re.compile(r"^\[aeko-hub\] \[(?P<module>\w+)\] \[[^\]]+\] (?P<description>.*)$")

USER_ROUTE_TEMPLATE = "/ai/user/{id_external_user}"

METRIC_DOCUMENT = {
    "_id": "65a8b3d6c0f8e1d7f4b2c0aa",
    "latency": "12.4ms",
    "response_status": 200,
    "endpoint": USER_ROUTE_TEMPLATE,
    "origin": "internal",
}


def build_metric(**overrides) -> Metric:
    """Build a metric fixture with optional field overrides."""
    fields = {
        "latency": "12.4ms",
        "response_status": 200,
        "endpoint": USER_ROUTE_TEMPLATE,
        "origin": "internal",
    }
    fields.update(overrides)
    return Metric(**fields)


@pytest.fixture(autouse=True)
def no_color(monkeypatch):
    """Disable color output for deterministic log assertions."""
    monkeypatch.delenv('AEKO_LOG_COLOR', raising=False)


@pytest.fixture
def recorded():
    """Capture metric sink calls for the duration of the test."""
    events = []
    set_event_sink(events.append)
    yield events
    set_event_sink(None)


def entries(capsys):
    """Parse captured log output into module and description pairs."""
    parsed = []
    for line in capsys.readouterr().out.splitlines():
        match = LINE.match(line)
        if match:
            parsed.append((match["module"], match["description"]))
    return parsed


def descriptions(capsys, module):
    """Return captured operation descriptions for the selected module."""
    return [description for name, description in entries(capsys) if name == module]


def test_a_metric_carries_the_three_fields_of_one_request():
    """Verify that a metric carries the three fields of one request."""
    metric = build_metric()

    assert metric.latency == "12.4ms"
    assert metric.response_status == 200
    assert metric.endpoint == USER_ROUTE_TEMPLATE


def test_a_metric_may_arrive_without_an_identifier():
    """Verify that a metric may arrive without an identifier."""
    assert build_metric().id is None


def test_a_metric_can_be_built_with_the_identifier_it_was_stored_under():
    """Verify that a metric can be built with the identifier it was stored under."""
    assert build_metric(id=METRIC_DOCUMENT["_id"]).id == METRIC_DOCUMENT["_id"]


def test_the_write_query_is_the_document_the_dashboard_reads(monkeypatch):
    """Verify that the write query is the document the dashboard reads."""
    monkeypatch.setattr(
        q,
        "datetime",
        SimpleNamespace(utcnow=lambda: CREATED_AT),
    )
    assert q.create_metric_query(build_metric()) == {
        "latency": "12.4ms",
        "response_status": 200,
        "endpoint": USER_ROUTE_TEMPLATE,
        "origin": "internal",
        "created_at": CREATED_AT,
    }


def test_the_write_query_stores_the_identifier_the_caller_was_answered_with():
    """Verify that the write query stores the identifier the caller was answered with."""
    document = q.create_metric_query(build_metric(id=METRIC_DOCUMENT["_id"]))

    assert document["_id"] == ObjectId(METRIC_DOCUMENT["_id"])


def test_a_metric_without_an_identifier_lets_mongo_assign_one():
    """Verify that a metric without an identifier lets mongo assign one."""
    assert "_id" not in q.create_metric_query(build_metric())


def test_the_read_query_matches_every_row():
    """Verify that the read query matches every row."""
    query, projection = q.get_all_metrics_query()

    assert query == {}
    assert projection == {}


def build_repository(collection=None):
    """Build a repository backed by configurable MongoDB doubles."""
    database = StubDatabase(hub_metrics=collection or StubCollection())
    return Repository(database), database


def test_repository_implements_the_repository_interface():
    """Verify that repository implements the repository interface."""
    assert issubclass(Repository, IRepository)
    assert Repository.__abstractmethods__ == frozenset()


def test_creating_a_metric_stores_the_document(monkeypatch):
    """Verify that creating a metric stores the document."""
    monkeypatch.setattr(
        q,
        "datetime",
        SimpleNamespace(utcnow=lambda: CREATED_AT),
    )
    repository, database = build_repository()

    repository.create_metric(build_metric())

    (document,) = database.hub_metrics.call_args("insert_one")[0]
    assert document == q.create_metric_query(build_metric())


def test_creating_a_metric_returns_it_with_the_identifier_mongo_assigned():
    """Verify that creating a metric returns it with the identifier mongo assigned."""
    repository, _ = build_repository(StubCollection(inserted_id="65a8b3d6c0f8e1d7f4b2c0aa"))

    stored = repository.create_metric(build_metric())

    assert stored.id == "65a8b3d6c0f8e1d7f4b2c0aa"


def test_a_write_that_fails_is_reported_as_a_database_error():
    """Verify that a write that fails is reported as a database error."""
    repository, _ = build_repository(StubCollection(error=ConnectionError("connection refused")))

    with pytest.raises(RuntimeError, match="connection refused"):
        repository.create_metric(build_metric())


def test_reading_the_metrics_maps_every_document():
    """Verify that reading the metrics maps every document."""
    repository, _ = build_repository(StubCollection(find_result=[METRIC_DOCUMENT]))

    (metric,) = repository.get_all_metrics()

    assert metric.id == METRIC_DOCUMENT["_id"]
    assert metric.latency == "12.4ms"
    assert metric.response_status == 200
    assert metric.endpoint == USER_ROUTE_TEMPLATE
    assert metric.origin == "internal"


def test_an_empty_collection_reads_as_an_empty_list():
    """Verify that an empty collection reads as an empty list."""
    repository, _ = build_repository(StubCollection(find_result=[]))

    assert repository.get_all_metrics() == []


def test_a_read_that_fails_is_reported_as_a_database_error():
    """Verify that a read that fails is reported as a database error."""
    repository, _ = build_repository(StubCollection(error=ConnectionError("connection refused")))

    with pytest.raises(RuntimeError, match="connection refused"):
        repository.get_all_metrics()


def test_a_document_missing_fields_still_becomes_a_metric():
    """Verify that a document missing fields still becomes a metric."""
    metric = metric_from_data({"_id": "1"})

    assert metric.id == "1"
    assert metric.latency == ""
    assert metric.response_status == 0


def test_both_repository_methods_are_logged_as_database_operations(capsys):
    """Verify that both repository methods are logged as database operations."""
    repository, _ = build_repository(StubCollection(find_result=[]))

    repository.create_metric(build_metric())
    repository.get_all_metrics()

    written = descriptions(capsys, "database")
    assert written[0].startswith("hub_metrics.create_metric succeeded in ")
    assert written[1].startswith("hub_metrics.get_all_metrics succeeded in ")


class StubMetricsRepository:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    def _run(self, name, *args):
        self.calls.append((name, *args))
        if self.error is not None:
            raise self.error
        return self.result

    def create_metric(self, metric):
        """Persist a metric and return it with its database identifier."""
        return self._run("create_metric", metric)

    def get_all_metrics(self):
        """Retrieve all stored metrics."""
        return self._run("get_all_metrics")


def test_service_implements_the_service_interface():
    """Verify that service implements the service interface."""
    assert issubclass(Service, IService)
    assert Service.__abstractmethods__ == frozenset()


def test_adding_a_metric_reaches_the_repository():
    """Verify that adding a metric reaches the repository."""
    repository = StubMetricsRepository()
    metric = build_metric()

    Service(repository).add_metric(metric)

    assert repository.calls == [("create_metric", metric)]


def test_adding_a_metric_returns_what_was_stored():
    """Verify that adding a metric returns what was stored."""
    stored = build_metric(id="1")

    assert Service(StubMetricsRepository(result=stored)).add_metric(build_metric()) is stored


def test_a_failed_write_becomes_a_runtime_error():
    """Verify that a failed write becomes a runtime error."""
    service = Service(StubMetricsRepository(error=RuntimeError("mongo exploded")))

    with pytest.raises(RuntimeError, match="mongo exploded"):
        service.add_metric(build_metric())


def test_reading_the_metrics_reaches_the_repository():
    """Verify that reading the metrics reaches the repository."""
    repository = StubMetricsRepository(result=[build_metric()])

    assert len(Service(repository).get_all_metrics()) == 1
    assert repository.calls == [("get_all_metrics",)]


def test_a_failed_read_becomes_a_runtime_error():
    """Verify that a failed read becomes a runtime error."""
    service = Service(StubMetricsRepository(error=RuntimeError("mongo exploded")))

    with pytest.raises(RuntimeError, match="mongo exploded"):
        service.get_all_metrics()


EVENT = Event(
    id_request=METRIC_DOCUMENT["_id"],
    latency="12.4ms",
    response_status=200,
    endpoint="/x",
    origin="internal",
)


def test_an_event_carries_exactly_what_a_metric_needs():
    """Verify that an event carries exactly what a metric needs."""
    assert EVENT.id_request == METRIC_DOCUMENT["_id"]
    assert EVENT.latency == "12.4ms"
    assert EVENT.response_status == 200
    assert EVENT.endpoint == "/x"


def test_nothing_is_recorded_when_no_sink_is_registered():
    """Verify that nothing is recorded when no sink is registered."""
    assert record_event(EVENT) is False


def test_a_registered_sink_receives_the_event(recorded):
    """Verify that a registered sink receives the event."""
    assert record_event(EVENT) is True
    assert recorded == [EVENT]


def test_the_sink_can_be_taken_back_off():
    """Verify that the sink can be taken back off."""
    events = []
    set_event_sink(events.append)
    set_event_sink(None)

    assert record_event(EVENT) is False
    assert events == []


def test_a_sink_that_raises_is_given_up_on_rather_than_propagated(capsys):
    """Verify that a sink that raises is given up on rather than propagated."""

    def explode(event):
        """Raise the configured failure to exercise error handling."""
        raise RuntimeError("connection refused")

    set_event_sink(explode)
    try:
        assert record_event(EVENT) is False
    finally:
        set_event_sink(None)

    assert descriptions(capsys, "database")[0].startswith("hub_metrics.record gave up: ")


def test_every_request_identifier_is_its_own():
    """Verify that every request identifier is its own."""
    assert new_id_request() != new_id_request()


def test_the_request_identifier_is_the_one_mongo_will_store_it_under():
    """Verify that the request identifier is the one mongo will store it under."""
    assert ObjectId.is_valid(new_id_request())


def test_the_endpoint_is_the_route_template_not_the_path_that_was_asked_for():
    """Verify that the endpoint is the route template not the path that was asked for."""
    scope = {
        "type": "http",
        "path": "/ai/user/12345",
        "route": SimpleNamespace(path=USER_ROUTE_TEMPLATE),
    }

    assert endpoint_of(scope) == USER_ROUTE_TEMPLATE


def test_a_path_that_matched_no_route_is_kept_as_it_came():
    """Verify that a path that matched no route is kept as it came."""
    assert endpoint_of({"type": "http", "path": "/no-such-endpoint"}) == "/no-such-endpoint"


def test_a_route_that_carries_no_template_falls_back_to_the_path():
    """Verify that a route that carries no template falls back to the path."""
    scope = {"type": "http", "path": "/mounted/thing", "route": SimpleNamespace()}

    assert endpoint_of(scope) == "/mounted/thing"


def test_a_scope_without_even_a_path_still_produces_a_row():
    """Verify that a scope without even a path still produces a row."""
    assert endpoint_of({"type": "http"}) == UNKNOWN_ENDPOINT


def build_app(operations=(), status=200, raises=None):
    """Build an ASGI application with configurable response behavior."""
    async def app(scope, receive, send):
        """Serve the simulated ASGI response used by the test."""
        for module, name in operations:
            with operation(module, name):
                pass

        if raises is not None:
            raise raises

        await send({"type": "http.response.start", "status": status, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    return app


async def call(app, method="GET", path="/x", sent=None):
    """Invoke the ASGI application with a simulated request scope."""
    async def receive():
        """Supply a simulated ASGI request message."""
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        """Send or capture the request messages used by the test."""
        if sent is not None:
            sent.append(message)

    await app({"type": "http", "method": method, "path": path, "query_string": b""}, receive, send)


def answered_ids(sent):
    """Extract request identifiers from captured ASGI response headers."""
    return [
        value.decode()
        for message in sent
        if message["type"] == "http.response.start"
        for name, value in message["headers"]
        if name == REQUEST_ID_HEADER.encode()
    ]


def test_a_request_leaves_exactly_one_event(recorded):
    """Verify that a request leaves exactly one event."""
    asyncio.run(call(RequestLogMiddleware(build_app([(Module.DATABASE, "user.get_user")]))))

    assert len(recorded) == 1


def test_the_event_carries_the_status_that_was_answered(recorded):
    """Verify that the event carries the status that was answered."""
    asyncio.run(call(RequestLogMiddleware(build_app(status=404))))

    assert recorded[0].response_status == 404


def test_the_event_carries_the_path_of_the_request(recorded):
    """Verify that the event carries the path of the request."""
    asyncio.run(call(RequestLogMiddleware(build_app()), path="/one"))

    assert recorded[0].endpoint == "/one"


def test_the_event_latency_is_the_one_the_block_reports(capsys, recorded):
    """Verify that the event latency is the one the block reports."""
    asyncio.run(call(RequestLogMiddleware(build_app())))

    headers = [HEADER.match(line) for line in capsys.readouterr().out.splitlines()]
    (header,) = [match for match in headers if match]
    assert f" in {recorded[0].latency}" in header["description"]


def test_two_requests_are_two_rows_with_two_identifiers(recorded):
    """Verify that two requests are two rows with two identifiers."""
    app = RequestLogMiddleware(build_app())

    asyncio.run(call(app, path="/one"))
    asyncio.run(call(app, path="/two"))

    first, second = recorded
    assert first.id_request != second.id_request


def test_a_request_that_ran_no_operation_is_still_tracked(recorded):
    """Verify that a request that ran no operation is still tracked."""
    asyncio.run(call(RequestLogMiddleware(build_app())))

    assert len(recorded) == 1


def test_a_request_that_crashed_is_tracked_as_a_server_error(recorded):
    """Verify that a request that crashed is tracked as a server error."""
    app = RequestLogMiddleware(build_app(raises=RuntimeError("boom")))

    with pytest.raises(RuntimeError):
        asyncio.run(call(app))

    assert recorded[0].response_status == CRASHED_STATUS


def test_a_lifespan_message_is_not_a_request_and_leaves_no_row(recorded):
    """Verify that a lifespan message is not a request and leaves no row."""
    async def app(scope, receive, send):
        """Serve the simulated ASGI response used by the test."""
        return None

    asyncio.run(RequestLogMiddleware(app)({"type": "lifespan"}, None, None))

    assert recorded == []


def test_a_sink_that_fails_does_not_fail_the_request(capsys):
    """Verify that a sink that fails does not fail the request."""
    def explode(event):
        """Raise the configured failure to exercise error handling."""
        raise RuntimeError("connection refused")

    set_event_sink(explode)
    try:
        asyncio.run(call(RequestLogMiddleware(build_app())))
    finally:
        set_event_sink(None)

    assert any(HEADER.match(line) for line in capsys.readouterr().out.splitlines())


def test_the_row_is_written_before_the_block_closes(capsys):
    """Verify that the row is written before the block closes."""

    def sink(event):
        """Capture or reject the metric supplied by the test scenario."""
        with operation(Module.DATABASE, "hub_metrics.create_metric"):
            pass

    set_event_sink(sink)
    try:
        asyncio.run(call(RequestLogMiddleware(build_app())))
    finally:
        set_event_sink(None)

    lines = capsys.readouterr().out.splitlines()
    assert "(1 operation)" in lines[0]
    assert "hub_metrics.create_metric" in lines[1]


def test_the_response_carries_the_identifier_back_to_the_caller():
    """Verify that the response carries the identifier back to the caller."""
    sent = []

    asyncio.run(call(RequestLogMiddleware(build_app()), sent=sent))

    assert len(answered_ids(sent)) == 1


def test_the_header_is_the_identifier_the_row_was_stored_under(recorded):
    """Verify that the header is the identifier the row was stored under."""
    sent = []

    asyncio.run(call(RequestLogMiddleware(build_app()), sent=sent))

    assert answered_ids(sent) == [recorded[0].id_request]


def test_two_requests_are_answered_with_two_identifiers():
    """Verify that two requests are answered with two identifiers."""
    first, second = [], []
    app = RequestLogMiddleware(build_app())

    asyncio.run(call(app, sent=first))
    asyncio.run(call(app, sent=second))

    assert answered_ids(first) != answered_ids(second)


def test_a_failing_response_carries_it_too():
    """Verify that a failing response carries it too."""
    sent = []

    asyncio.run(call(RequestLogMiddleware(build_app(status=500)), sent=sent))

    assert len(answered_ids(sent)) == 1


def test_the_headers_the_application_set_are_kept():
    """Verify that the headers the application set are kept."""
    sent = []

    async def app(scope, receive, send):
        """Serve the simulated ASGI response used by the test."""
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send({"type": "http.response.body", "body": b""})

    asyncio.run(call(RequestLogMiddleware(app), sent=sent))

    names = [name for name, _ in sent[0]["headers"]]
    assert b"content-type" in names
    assert REQUEST_ID_HEADER.encode() in names


def test_an_identifier_the_application_wrote_itself_is_replaced_not_added_to():
    """Verify that an identifier the application wrote itself is replaced not added to."""
    sent = []

    async def app(scope, receive, send):
        """Serve the simulated ASGI response used by the test."""
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(REQUEST_ID_HEADER.encode(), b"made-up")],
            }
        )
        await send({"type": "http.response.body", "body": b""})

    asyncio.run(call(RequestLogMiddleware(app), sent=sent))

    (answered,) = answered_ids(sent)
    assert answered != "made-up"


def test_a_response_that_never_started_has_nowhere_to_carry_it():
    """Verify that a response that never started has nowhere to carry it."""
    sent = []
    app = RequestLogMiddleware(build_app(raises=RuntimeError("boom")))

    with pytest.raises(RuntimeError):
        asyncio.run(call(app, sent=sent))

    assert answered_ids(sent) == []


def test_the_real_application_answers_with_the_identifier_of_the_stored_row(api_main):
    """Verify that the real application answers with the identifier of the stored row."""
    with TestClient(api_main.app) as client:
        response = client.get("/ai/user/12345")
        stored = list(api_main.db["hub_metrics"].documents)

    assert response.headers["X-Request-Id"] == str(stored[0]["_id"])


def test_the_metrics_list_route_is_not_exposed(api_main):
    """Verify that the public metrics list route was removed."""
    with TestClient(api_main.app) as client:
        response = client.get(ROUTE)
    assert response.status_code == 404


def test_the_lifespan_registers_a_sink_and_takes_it_back_off(api_main):
    """Verify that the lifespan registers a sink and takes it back off."""
    with TestClient(api_main.app):
        assert event_tracking._sink is not None

    assert event_tracking._sink is None


def test_every_request_of_the_real_application_lands_in_the_collection(api_main):
    """Verify that every request of the real application lands in the collection."""
    with TestClient(api_main.app) as client:
        client.get("/no-such-endpoint")
        stored = list(api_main.db["hub_metrics"].documents)

    assert len(stored) == 1
    assert stored[0]["response_status"] == 404
    assert stored[0]["endpoint"] == "/no-such-endpoint"
    assert stored[0]["latency"].endswith("ms")
    assert stored[0]["origin"] == "internal"
    assert isinstance(stored[0]["created_at"], datetime)
    assert str(stored[0]["_id"])


def test_the_mcp_root_path_is_openai():
    """Verify that the MCP root path is openai."""
    assert origin_of("/ai/mcp") == "openai"


def test_an_mcp_subpath_is_openai():
    """Verify that an MCP subpath is openai."""
    assert origin_of("/ai/mcp/.well-known/oauth-protected-resource") == "openai"


def test_an_mcp_trailing_slash_is_openai():
    """Verify that an MCP trailing slash is openai."""
    assert origin_of("/ai/mcp/") == "openai"


def test_a_lookalike_mcp_path_is_openai():
    """Verify that any path containing mcp is openai."""
    assert origin_of("/ai/mcp-extra") == "openai"


def test_a_path_that_only_contains_mcp_is_openai():
    """Verify that a path is openai when it contains mcp without the API prefix."""
    assert origin_of("/mcp") == "openai"


def test_a_rest_path_is_internal():
    """Verify that a REST path is internal."""
    assert origin_of("/ai/user/12345") == "internal"


def test_the_application_mcp_prefix_is_openai(api_main):
    """Verify that the application MCP prefix is openai."""
    assert origin_of(api_main.CHATGPT_MCP_PREFIX) == "openai"


def test_a_mcp_request_is_stored_as_openai(recorded):
    """Verify that an MCP request is stored as openai."""
    asyncio.run(call(RequestLogMiddleware(build_app()), path="/ai/mcp"))
    assert recorded[0].origin == "openai"


def test_a_rest_request_is_stored_as_internal(recorded):
    """Verify that a REST request is stored as internal."""
    asyncio.run(call(RequestLogMiddleware(build_app()), path="/ai/user/12345"))
    assert recorded[0].origin == "internal"


def test_a_document_missing_origin_reads_as_internal():
    """Verify that a document missing origin reads as internal."""
    assert metric_from_data({"_id": "1"}).origin == "internal"


def test_a_document_missing_created_at_reads_as_unset():
    """Verify that a document missing created_at reads as unset."""
    assert metric_from_data({"_id": "1"}).created_at is None


def test_a_tracked_request_records_the_route_template(api_main):
    """Verify that a tracked request records the route template."""
    with TestClient(api_main.app) as client:
        client.get("/ai/user/12345")
        stored = list(api_main.db["hub_metrics"].documents)

    assert stored[0]["endpoint"] == USER_ROUTE_TEMPLATE
