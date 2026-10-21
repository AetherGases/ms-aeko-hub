"""Verify ChatGPT inventory ingest hides host files and Cloudinary fields."""

import socket

import pytest
import requests

from cmd.api.integrations.cloudinary_api import CloudinaryError
from cmd.api.integrations.inventory_api import InventoryError
from cmd.api.tools import inventory_tools
from tests.test_cloudinary_api import SIGNATURE_PAYLOAD


INVENTORY_POST_RESPONSE = {
    "id": 1,
    "name": "relatório",
    "type": "INPUT",
    "status": "PROCESSING",
    "createdAt": "2026-10-04T19:30:00",
    "storageFile": {
        "id": 10,
        "fileName": "inventorio.xlsx",
        "path": "https://cloudinary/sadjasoda",
        "createdAt": "2026-10-04T19:30:00",
    },
}

SECURE_URL = "https://cloudinary/sadjasoda"


class StubTickets:
    """Record ChatGPT inventory ids without creating Aether upload tickets."""

    def __init__(self):
        self.recorded = []
        self.created = {}

    def record_created_inventory(self, id_external_user, inventory_id):
        """Append a created inventory id for later analysis polling."""
        self.recorded.append((id_external_user, inventory_id))
        self.created.setdefault(id_external_user, []).append(inventory_id)

    def created_inventory_ids(self, id_external_user):
        """Return inventory identifiers created for one user."""
        return list(self.created.get(id_external_user, []))


class StubCreateInventory:
    """Record inventory creation calls and return a scripted response."""

    def __init__(self):
        self.payload = dict(INVENTORY_POST_RESPONSE)
        self.error = None
        self.calls = []

    def __call__(self, name, file_name, path):
        """Create the scripted inventory or raise its configured error."""
        self.calls.append((name, file_name, path))
        if self.error is not None:
            raise self.error
        return self.payload


@pytest.fixture(autouse=True)
def chatgpt_file_allowed_hosts(monkeypatch):
    """Allow the ChatGPT test host and the production download host."""
    monkeypatch.setenv(
        "CHATGPT_FILE_ALLOWED_HOSTS",
        "files.chatgpt.example,files.oaiusercontent.com",
    )


@pytest.fixture(autouse=True)
def public_chatgpt_dns(monkeypatch):
    """Resolve allowlisted ChatGPT hosts to a public address."""

    def fake_getaddrinfo(host, port, *args, **kwargs):
        """Return a public IPv4 address for allowlisted ChatGPT hosts."""
        lowered = str(host).lower().rstrip(".")
        if lowered in {"files.chatgpt.example", "files.oaiusercontent.com"}:
            return [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("1.2.3.4", port or 443))
            ]
        raise OSError("name resolution failed")

    monkeypatch.setattr(inventory_tools.socket, "getaddrinfo", fake_getaddrinfo)


@pytest.fixture
def services():
    """Bind ticket and inventory doubles used by ChatGPT ingest."""
    tickets = StubTickets()
    create_inventory = StubCreateInventory()
    inventory_tools.configure(tickets=tickets, create_inventory=create_inventory)
    yield tickets, create_inventory
    inventory_tools.configure()


def _file_schema(parameters):
    """Return the nested JSON schema for the ChatGPT file argument."""
    properties = parameters["properties"]
    file_schema = properties["file"]
    if "$ref" in file_schema:
        name = file_schema["$ref"].rsplit("/", 1)[-1]
        return parameters["$defs"][name]
    return file_schema


def test_ingest_chatgpt_inventory_uploads_bytes_and_hides_path(monkeypatch, services):
    """Verify that ingest chatgpt inventory uploads bytes and hides path."""
    tickets, create_inventory = services
    signatures = []
    uploads = []

    monkeypatch.setattr(
        inventory_tools,
        "get_upload_signature",
        lambda file_type: signatures.append(file_type) or dict(SIGNATURE_PAYLOAD),
    )
    monkeypatch.setattr(
        inventory_tools,
        "upload_signed_file",
        lambda file_bytes, file_name, payload: uploads.append(
            (file_bytes, file_name, payload)
        )
        or SECURE_URL,
    )

    result = inventory_tools.ingest_chatgpt_inventory(
        12345,
        "relatório",
        "inventorio.xlsx",
        "XLSX",
        b"xlsx-bytes",
    )

    assert signatures == ["XLSX"]
    assert uploads == [(b"xlsx-bytes", "inventorio.xlsx", SIGNATURE_PAYLOAD)]
    assert create_inventory.calls == [("relatório", "inventorio.xlsx", SECURE_URL)]
    assert tickets.recorded == [(12345, 1)]
    assert result == {
        "id": 1,
        "name": "relatório",
        "type": "INPUT",
        "status": "PROCESSING",
        "createdAt": "2026-10-04T19:30:00",
    }
    assert "path" not in result
    assert "storageFile" not in result
    assert "signature" not in result


def test_ingest_chatgpt_inventory_rejects_unknown_file_type_before_ms(monkeypatch, services):
    """Verify that ingest chatgpt inventory rejects unknown file type before ms."""
    tickets, create_inventory = services
    called = []

    monkeypatch.setattr(
        inventory_tools,
        "get_upload_signature",
        lambda file_type: called.append("signature") or SIGNATURE_PAYLOAD,
    )
    monkeypatch.setattr(
        inventory_tools,
        "upload_signed_file",
        lambda *args, **kwargs: called.append("upload") or SECURE_URL,
    )

    with pytest.raises(ValueError, match="fileType"):
        inventory_tools.ingest_chatgpt_inventory(
            12345,
            "relatório",
            "inventorio.csv",
            "CSV",
            b"csv-bytes",
        )

    assert called == []
    assert create_inventory.calls == []
    assert tickets.recorded == []


def test_ingest_chatgpt_inventory_does_not_index_when_create_fails(monkeypatch, services):
    """Verify that ingest chatgpt inventory does not index when create fails."""
    tickets, create_inventory = services
    create_inventory.error = InventoryError("ms-inventory down")
    monkeypatch.setattr(inventory_tools, "get_upload_signature", lambda file_type: SIGNATURE_PAYLOAD)
    monkeypatch.setattr(inventory_tools, "upload_signed_file", lambda *args, **kwargs: SECURE_URL)

    with pytest.raises(RuntimeError, match="Inventory submission failed. Try again later."):
        inventory_tools.ingest_chatgpt_inventory(
            12345,
            "relatório",
            "inventorio.xlsx",
            "XLSX",
            b"xlsx-bytes",
        )

    assert tickets.recorded == []


@pytest.mark.parametrize(
    "error",
    [
        CloudinaryError("signature=a1b2c3d4e5f6 path=https://cloudinary/sadjasoda"),
        InventoryError("download_url=https://files.chatgpt.example/tmp"),
    ],
)
def test_ingest_chatgpt_inventory_hides_microservice_details(monkeypatch, services, error):
    """Verify that ingest chatgpt inventory hides microservice details."""
    tickets, create_inventory = services
    if isinstance(error, CloudinaryError):
        monkeypatch.setattr(
            inventory_tools,
            "get_upload_signature",
            lambda file_type: (_ for _ in ()).throw(error),
        )
    else:
        monkeypatch.setattr(inventory_tools, "get_upload_signature", lambda file_type: SIGNATURE_PAYLOAD)
        monkeypatch.setattr(inventory_tools, "upload_signed_file", lambda *args, **kwargs: SECURE_URL)
        create_inventory.error = error

    with pytest.raises(RuntimeError) as raised:
        inventory_tools.ingest_chatgpt_inventory(
            12345,
            "relatório",
            "inventorio.xlsx",
            "XLSX",
            b"xlsx-bytes",
        )

    message = str(raised.value)
    assert message == "Inventory submission failed. Try again later."
    assert "signature" not in message
    assert "path" not in message
    assert "download_url" not in message
    assert tickets.recorded == []


def test_chatgpt_analyze_inventory_fetches_download_url_and_hides_it(monkeypatch):
    """Verify that chatgpt analyze inventory fetches download_url and hides it."""
    from cmd.api.acl.open_ai import identity
    from cmd.api.acl.open_ai.catalog import get_chatgpt_tools
    from cmd.api.tools import inventory_tools

    downloaded = []

    def fake_get(url, **kwargs):
        """Record the ChatGPT download URL and timeout."""
        downloaded.append((url, kwargs.get("timeout")))
        class Response:
            status_code = 200
            content = b"xlsx-bytes"
            def raise_for_status(self):
                """Accept the scripted successful download."""
                return None
            def close(self):
                """Release the scripted download."""
                return None
            def iter_content(self, chunk_size=8192):
                """Yield the scripted ChatGPT file bytes."""
                yield self.content
        return Response()

    monkeypatch.setattr(inventory_tools.requests, "get", fake_get)
    monkeypatch.setattr(inventory_tools, "ingest_chatgpt_inventory", lambda *args: {
        "id": 1, "name": args[1], "type": "INPUT", "status": "PROCESSING", "createdAt": "t"
    })
    tool = next(t for t in get_chatgpt_tools() if t.name == "analyze_inventory")
    token = identity.bind_id_external_user(12345)
    try:
        result = tool.func(
            name="relatório",
            fileType="XLSX",
            file={
                "download_url": "https://files.chatgpt.example/tmp",
                "file_id": "file_abc",
                "mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "file_name": "inventorio.xlsx",
            },
        )
    finally:
        identity.reset_id_external_user(token)
    assert downloaded == [("https://files.chatgpt.example/tmp", 60.0)]
    assert result["id"] == 1
    assert "download_url" not in result
    assert "file_id" not in result
    assert "path" not in result


@pytest.mark.parametrize("missing", ["download_url", "file_id"])
def test_fetch_chatgpt_file_rejects_incomplete_host_file_before_cloudinary(
    monkeypatch, missing
):
    """Verify that fetch chatgpt file rejects incomplete host files before cloudinary."""
    called = []
    monkeypatch.setattr(
        inventory_tools,
        "get_upload_signature",
        lambda file_type: called.append("signature") or SIGNATURE_PAYLOAD,
    )
    monkeypatch.setattr(
        inventory_tools.requests,
        "get",
        lambda *args, **kwargs: called.append("download") or None,
    )

    host_file = {
        "download_url": "https://files.chatgpt.example/tmp",
        "file_id": "file_abc",
        "file_name": "inventorio.xlsx",
    }
    del host_file[missing]

    with pytest.raises(ValueError):
        inventory_tools.fetch_chatgpt_file(host_file)

    assert called == []


@pytest.mark.parametrize(
    "download_url",
    [
        "http://files.chatgpt.example/tmp",
        "https://127.0.0.1/tmp",
    ],
)
def test_fetch_chatgpt_file_rejects_unsafe_download_url_before_get(
    monkeypatch, download_url
):
    """Verify that fetch chatgpt file does not GET http or loopback URLs."""
    called = []
    monkeypatch.setattr(
        inventory_tools.requests,
        "get",
        lambda *args, **kwargs: called.append((args, kwargs)) or None,
    )

    with pytest.raises(RuntimeError) as raised:
        inventory_tools.fetch_chatgpt_file(
            {
                "download_url": download_url,
                "file_id": "file_abc",
                "file_name": "inventorio.xlsx",
            }
        )

    message = str(raised.value)
    assert message == "Inventory submission failed. Try again later."
    assert download_url not in message
    assert called == []


def test_fetch_chatgpt_file_rejects_oversized_body(monkeypatch):
    """Verify that fetch chatgpt file rejects a body larger than the byte cap."""
    monkeypatch.setenv("CHATGPT_FILE_MAX_BYTES", "10")

    class Response:
        status_code = 200
        content = b"x" * 11

        def raise_for_status(self):
            """Accept the scripted successful download headers."""
            return None

        def close(self):
            """Release the scripted download."""
            return None

        def iter_content(self, chunk_size=8192):
            """Yield the oversized ChatGPT file body."""
            yield self.content

    called = []

    def fake_get(*args, **kwargs):
        """Record that the download was attempted for an allowed URL."""
        called.append((args, kwargs))
        return Response()

    monkeypatch.setattr(inventory_tools.requests, "get", fake_get)

    with pytest.raises(RuntimeError) as raised:
        inventory_tools.fetch_chatgpt_file(
            {
                "download_url": "https://files.chatgpt.example/tmp",
                "file_id": "file_abc",
                "file_name": "inventorio.xlsx",
            }
        )

    message = str(raised.value)
    assert message == "Inventory submission failed. Try again later."
    assert "https://files.chatgpt.example/tmp" not in message
    assert called
    assert called[0][0][0] == "https://files.chatgpt.example/tmp"
    assert called[0][1].get("allow_redirects") is False


@pytest.mark.parametrize(
    "location",
    [
        "http://192.168.1.10/steal",
        "https://169.254.169.254/latest/meta-data/",
    ],
)
def test_fetch_chatgpt_file_does_not_follow_redirect_to_private_or_metadata(
    monkeypatch, location
):
    """Verify that fetch chatgpt file does not follow a 302 to RFC1918 or metadata."""
    fetched = []

    class RedirectResponse:
        status_code = 302
        headers = {"Location": location}
        content = b""

        def raise_for_status(self):
            """A 302 is not an HTTP error for requests.raise_for_status."""
            return None

        def close(self):
            """Release the scripted redirect response."""
            return None

        def iter_content(self, chunk_size=8192):
            """Yield no file bytes for a redirect response."""
            if False:
                yield b""

    def fake_get(url, **kwargs):
        """Record each GET and refuse to follow Location."""
        fetched.append((url, kwargs.get("allow_redirects")))
        if url == location:
            raise AssertionError("redirect Location must not be fetched")
        return RedirectResponse()

    monkeypatch.setattr(inventory_tools.requests, "get", fake_get)

    with pytest.raises(RuntimeError) as raised:
        inventory_tools.fetch_chatgpt_file(
            {
                "download_url": "https://files.chatgpt.example/tmp",
                "file_id": "file_abc",
                "file_name": "inventorio.xlsx",
            }
        )

    message = str(raised.value)
    assert message == "Inventory submission failed. Try again later."
    assert location not in message
    assert fetched == [("https://files.chatgpt.example/tmp", False)]


def test_fetch_chatgpt_file_denies_when_dns_raises_oserror(monkeypatch):
    """Verify that fetch chatgpt file denies the download when DNS raises OSError."""
    called = []
    monkeypatch.setattr(
        inventory_tools.socket,
        "getaddrinfo",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("name resolution failed")),
    )
    monkeypatch.setattr(
        inventory_tools.requests,
        "get",
        lambda *args, **kwargs: called.append((args, kwargs)) or None,
    )

    with pytest.raises(RuntimeError) as raised:
        inventory_tools.fetch_chatgpt_file(
            {
                "download_url": "https://files.chatgpt.example/tmp",
                "file_id": "file_abc",
                "file_name": "inventorio.xlsx",
            }
        )

    message = str(raised.value)
    assert message == "Inventory submission failed. Try again later."
    assert "files.chatgpt.example" not in message
    assert called == []


def test_fetch_chatgpt_file_rejects_host_outside_allowlist(monkeypatch):
    """Verify that fetch chatgpt file rejects a host outside the ChatGPT allowlist."""
    called = []
    monkeypatch.setattr(
        inventory_tools.requests,
        "get",
        lambda *args, **kwargs: called.append((args, kwargs)) or None,
    )

    with pytest.raises(RuntimeError) as raised:
        inventory_tools.fetch_chatgpt_file(
            {
                "download_url": "https://evil.example/tmp",
                "file_id": "file_abc",
                "file_name": "inventorio.xlsx",
            }
        )

    message = str(raised.value)
    assert message == "Inventory submission failed. Try again later."
    assert "evil.example" not in message
    assert called == []


def test_fetch_chatgpt_file_maps_http_errors_without_leaking_the_url(monkeypatch):
    """Verify that fetch chatgpt file maps http errors without leaking the url."""
    class Response:
        status_code = 403
        content = b""

        def raise_for_status(self):
            """Surface the scripted ChatGPT download failure."""
            raise requests.HTTPError("403 for https://files.chatgpt.example/tmp")

    monkeypatch.setattr(inventory_tools.requests, "get", lambda *args, **kwargs: Response())

    with pytest.raises(RuntimeError) as raised:
        inventory_tools.fetch_chatgpt_file(
            {
                "download_url": "https://files.chatgpt.example/tmp",
                "file_id": "file_abc",
                "file_name": "inventorio.xlsx",
            }
        )

    message = str(raised.value)
    assert message == "Inventory submission failed. Try again later."
    assert "https://files.chatgpt.example/tmp" not in message
    assert "download_url" not in message


def test_chatgpt_catalog_analyze_inventory_uses_host_file_schema():
    """Verify that chatgpt catalog analyze inventory uses host file schema."""
    from cmd.api.acl.open_ai.catalog import get_chatgpt_tools
    from cmd.api.acl.open_ai.server import build_mcp_server

    tool = next(item for item in get_chatgpt_tools() if item.name == "analyze_inventory")
    assert set(tool.args) == {"name", "fileType", "file"}
    assert "ticket" not in tool.args
    assert "fileName" not in tool.args
    assert "id_external_user" not in tool.args

    registered = {
        item.name: item.parameters
        for item in build_mcp_server()._tool_manager.list_tools()
    }
    analyze = registered["analyze_inventory"]
    assert set(analyze["properties"]) == {"name", "fileType", "file"}
    file_schema = _file_schema(analyze)
    assert set(file_schema["properties"]) == {
        "download_url",
        "file_id",
        "mime_type",
        "file_name",
    }
    assert set(file_schema["required"]) == {"download_url", "file_id"}
    assert set(registered["get_inventory_analysis"]["properties"]) == {"id"}


def test_chatgpt_inventory_descriptions_omit_aether_tickets():
    """Verify that chatgpt inventory descriptions omit aether tickets."""
    from cmd.api.acl.open_ai.catalog import get_chatgpt_tools
    from cmd.api.acl.open_ai.server import build_mcp_server

    descriptions = {tool.name: tool.description for tool in get_chatgpt_tools()}
    registered = {
        tool.name: tool.description
        for tool in build_mcp_server()._tool_manager.list_tools()
    }
    analyze = descriptions["analyze_inventory"]
    polling = descriptions["get_inventory_analysis"]

    for text in (analyze, registered["analyze_inventory"], polling, registered["get_inventory_analysis"]):
        assert "Aether app" not in text
        assert "ticket" not in text
        assert "id_external_user" not in text
    assert "IMAGE" in analyze and "XLSX" in analyze
    assert "get_inventory_analysis" in analyze
    assert "PROCESSING" in polling
    assert "analyze_inventory" in polling


def test_record_created_inventory_allows_get_inventory_analysis(services):
    """Verify that record created inventory allows get inventory analysis."""
    from cmd.api.acl.open_ai import identity
    from cmd.api.acl.open_ai.catalog import get_chatgpt_tools
    from improvement_plan.entity import ImprovementPlan

    tickets, _ = services
    tickets.record_created_inventory(12345, 1)

    class Plans:
        def get_by_id_external_inventory(self, identifier):
            """Return a plan for the ingested inventory."""
            return ImprovementPlan(
                id_external_inventory=identifier,
                id_external_company=90,
                defined_problem="high scope 1",
                method="replace boilers",
                reasoning="combustion",
            )

    inventory_tools.configure(tickets=tickets, plans=Plans())
    tool = next(item for item in get_chatgpt_tools() if item.name == "get_inventory_analysis")
    user_token = identity.bind_id_external_user(12345)
    company_token = identity.bind_id_external_company(90)
    try:
        result = tool.func(id=1)
    finally:
        identity.reset_id_external_company(company_token)
        identity.reset_id_external_user(user_token)

    assert result == {
        "defined_problem": "high scope 1",
        "solving_method": "replace boilers",
        "reasoning": "combustion",
    }


def test_get_inventory_analysis_rejects_other_company_even_when_redis_has_id(services):
    """Verify that analysis of another company's inventory is rejected even if Redis lists the id."""
    from cmd.api.acl.open_ai import identity
    from cmd.api.acl.open_ai.catalog import get_chatgpt_tools
    from improvement_plan.entity import ImprovementPlan

    tickets, _ = services
    tickets.record_created_inventory(12345, 99)

    class Plans:
        def get_by_id_external_inventory(self, identifier):
            """Return a plan owned by a different company."""
            return ImprovementPlan(
                id_external_inventory=identifier,
                id_external_company=91,
                defined_problem="foreign plan",
                method="should not leak",
                reasoning="other tenant",
            )

    inventory_tools.configure(tickets=tickets, plans=Plans())
    tool = next(item for item in get_chatgpt_tools() if item.name == "get_inventory_analysis")
    user_token = identity.bind_id_external_user(12345)
    company_token = identity.bind_id_external_company(90)
    try:
        with pytest.raises(ValueError, match="inventory"):
            tool.func(id=99)
    finally:
        identity.reset_id_external_company(company_token)
        identity.reset_id_external_user(user_token)
