"""Verify the ChatGPT inventory widget resource and fileParams metadata."""

from pathlib import Path


INVENTORY_WIDGET_URI = "ui://widget/analyze-inventory.html"
INVENTORY_WIDGET_MIME = "text/html;profile=mcp-app"


def test_analyze_inventory_declares_widget_and_file_params():
    """Verify that analyze inventory declares the in-chat widget and file params."""
    from cmd.api.acl.open_ai.server import build_mcp_server

    tool = next(
        item
        for item in build_mcp_server()._tool_manager.list_tools()
        if item.name == "analyze_inventory"
    )
    meta = tool.meta
    assert meta["ui"]["resourceUri"] == INVENTORY_WIDGET_URI
    assert meta["openai/outputTemplate"] == INVENTORY_WIDGET_URI
    assert meta["openai/fileParams"] == ["file"]


def test_inventory_widget_html_is_a_self_contained_form():
    """Verify that inventory widget html is a self contained form."""
    html = Path("cmd/api/acl/open_ai/widgets/analyze_inventory.html").read_text(
        encoding="utf-8"
    )
    assert 'name="name"' in html or 'id="name"' in html
    assert "IMAGE" in html and "XLSX" in html
    assert 'type="file"' in html
    assert "uploadFile" in html
    assert "callTool" in html
    assert "analyze_inventory" in html
    lower = html.lower()
    assert "signature" not in lower
    assert "cloudinary" not in lower
    assert "apikey" not in lower
    assert "api_key" not in lower


def test_inventory_widget_resource_is_listed_with_mcp_app_mime():
    """Verify that inventory widget resource is listed with mcp app mime."""
    from cmd.api.acl.open_ai.server import build_mcp_server

    resources = build_mcp_server()._resource_manager.list_resources()
    widget = next(item for item in resources if str(item.uri) == INVENTORY_WIDGET_URI)
    assert widget.mime_type == INVENTORY_WIDGET_MIME
