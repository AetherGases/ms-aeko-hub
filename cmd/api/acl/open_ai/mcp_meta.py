"""Build FastMCP tool metadata ChatGPT uses for Sign in."""

from cmd.api.acl.open_ai.constants import (
    AUTHENTICATED_CHATGPT_TOOL_NAMES,
    INVENTORY_WIDGET_URI,
)


def tool_meta(name: str) -> dict:
    """Return FastMCP tool metadata ChatGPT uses for Sign in and widgets."""
    if name in AUTHENTICATED_CHATGPT_TOOL_NAMES:
        schemes = [{"type": "oauth2", "scopes": ["mcp"]}]
    else:
        schemes = [{"type": "noauth"}]
    meta = {"securitySchemes": schemes}
    if name == "analyze_inventory":
        meta["ui"] = {"resourceUri": INVENTORY_WIDGET_URI}
        meta["openai/outputTemplate"] = INVENTORY_WIDGET_URI
        meta["openai/fileParams"] = ["file"]
    return meta
