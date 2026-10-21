"""Build the FastMCP server that serves the ChatGPT tool catalog over HTTP."""

import os
from pathlib import Path
from urllib.parse import urlparse

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from cmd.api.acl.mcp_server import run_in_worker_thread
from cmd.api.acl.open_ai.catalog import get_chatgpt_tools
from cmd.api.acl.open_ai.mcp_meta import INVENTORY_WIDGET_URI, tool_meta

SERVER_NAME = "aeko-chatgpt"
INVENTORY_WIDGET_MIME = "text/html;profile=mcp-app"
INVENTORY_WIDGET_PATH = (
    Path(__file__).resolve().parent / "widgets" / "analyze_inventory.html"
)


_LOCAL_HOSTS = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
_LOCAL_ORIGINS = [
    "http://127.0.0.1:*",
    "http://localhost:*",
    "http://[::1]:*",
    "https://127.0.0.1:*",
    "https://localhost:*",
    "https://[::1]:*",
]
_CHATGPT_ORIGINS = [
    "https://chatgpt.com",
    "https://chatgpt.com:*",
    "https://chat.openai.com",
    "https://chat.openai.com:*",
]
_BIND_ALL_HOSTS = frozenset({"0.0.0.0", "::", "[::]"})


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _hosts_from_url(url: str) -> tuple[list[str], list[str]]:
    parsed = urlparse((url or "").strip())
    hosts: list[str] = []
    origins: list[str] = []
    if not parsed.netloc:
        return hosts, origins
    hosts.append(parsed.netloc)
    if parsed.hostname:
        hosts.append(parsed.hostname)
        hosts.append(f"{parsed.hostname}:*")
    if parsed.scheme:
        origins.append(f"{parsed.scheme}://{parsed.netloc}")
    return hosts, origins


def _transport_security() -> TransportSecuritySettings:
    allowed_hosts: list[str] = []
    allowed_origins = list(_CHATGPT_ORIGINS)
    for value in (
        os.environ.get("OAUTH_ISSUER", ""),
        os.environ.get("OAUTH_AUDIENCE", ""),
    ):
        hosts, origins = _hosts_from_url(value)
        allowed_hosts.extend(hosts)
        allowed_origins.extend(origins)
    host = os.environ.get("HOST", "").strip()
    if host and host not in _BIND_ALL_HOSTS:
        allowed_hosts.append(host)
        allowed_hosts.append(f"{host}:*")
    if not allowed_hosts:
        allowed_hosts.extend(_LOCAL_HOSTS)
        allowed_origins.extend(_LOCAL_ORIGINS)
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=_unique(allowed_hosts),
        allowed_origins=_unique(allowed_origins),
    )


def build_mcp_server() -> FastMCP:
    """Create a FastMCP server with every ChatGPT tool registered.

    The streamable HTTP endpoint is served at the root path so a host
    application can choose the mount prefix. DNS rebinding protection is
    enabled. Request bodies are capped at 1 MiB, matching the MCP auth gate.
    """

    server = FastMCP(
        SERVER_NAME,
        streamable_http_path="/",
        transport_security=_transport_security(),
        max_request_body_size=1 * 1024 * 1024,
    )
    for tool in get_chatgpt_tools():
        server.add_tool(
            run_in_worker_thread(tool.func),
            name=tool.name,
            description=tool.description,
            meta=tool_meta(tool.name),
        )

    @server.resource(INVENTORY_WIDGET_URI, mime_type=INVENTORY_WIDGET_MIME)
    def analyze_inventory_widget() -> str:
        """Return the in-chat inventory upload form."""

        return INVENTORY_WIDGET_PATH.read_text(encoding="utf-8")

    return server


mcp = build_mcp_server()
