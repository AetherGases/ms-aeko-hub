"""Build the FastMCP server that serves the ChatGPT tool catalog over HTTP."""

import os
from urllib.parse import urlparse

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from cmd.api.acl.mcp_server import run_in_worker_thread
from cmd.api.acl.open_ai.catalog import get_chatgpt_tools
from cmd.api.acl.open_ai.constants import (
    INVENTORY_WIDGET_MIME,
    INVENTORY_WIDGET_PATH,
    INVENTORY_WIDGET_URI,
    SERVER_NAME,
    _BIND_ALL_HOSTS,
    _CHATGPT_ORIGINS,
    _LOCAL_HOSTS,
    _LOCAL_ORIGINS,
)
from cmd.api.acl.open_ai.mcp_meta import tool_meta


def _unique(values: list[str]) -> list[str]:
    """Return values in order with duplicates removed."""
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _hosts_from_url(url: str) -> tuple[list[str], list[str]]:
    """Extract allowed hosts and origins from a configured URL."""
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
    """Build DNS-rebinding protection settings for the MCP server."""
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
