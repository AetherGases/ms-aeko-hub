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


def _transport_security() -> TransportSecuritySettings:
    allowed_hosts = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
    allowed_origins = [
        "http://127.0.0.1:*",
        "http://localhost:*",
        "http://[::1]:*",
        "https://127.0.0.1:*",
        "https://localhost:*",
        "https://[::1]:*",
        "https://chatgpt.com",
        "https://chatgpt.com:*",
        "https://chat.openai.com",
        "https://chat.openai.com:*",
    ]
    issuer = os.environ.get("OAUTH_ISSUER", "").strip()
    if issuer:
        parsed = urlparse(issuer)
        if parsed.netloc:
            allowed_hosts.append(parsed.netloc)
            hostname = parsed.hostname
            if hostname:
                allowed_hosts.append(hostname)
                allowed_hosts.append(f"{hostname}:*")
            if parsed.scheme:
                allowed_origins.append(f"{parsed.scheme}://{parsed.netloc}")
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=allowed_hosts,
        allowed_origins=allowed_origins,
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
