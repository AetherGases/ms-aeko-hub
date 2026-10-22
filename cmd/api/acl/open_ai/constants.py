"""ChatGPT tool names, identity scope keys, widget paths, and transport hosts."""

from pathlib import Path

ANONYMOUS_CHATGPT_TOOL_NAMES = {
    "query_gases_info",
    "climatiq_search",
    "climatiq_estimate",
    "calculator",
    "calculate_roi",
    "calculate_payback",
}

AUTHENTICATED_CHATGPT_TOOL_NAMES = {
    "ask_aeko",
    "analyze_inventory",
    "get_inventory_analysis",
    "get_user_profile_by_external_id",
    "list_user_memory_fields",
    "get_user_memory_by_field",
    "list_user_memories",
    "list_user_session_names",
    "get_session_messages_by_name",
    "get_latest_session_messages",
    "count_user_sessions",
    "get_improvement_plan_by_inventory",
    "get_improvement_plan_problem",
    "get_improvement_plan_method",
    "get_improvement_plan_reasoning",
    "list_latest_improvement_plans",
    "query_improvement_plan_problems",
}

_SCOPE_STATE_KEY = "chatgpt_id_external_user"
_SCOPE_STATE_COMPANY_KEY = "chatgpt_id_external_company"
_SCOPE_STATE_MS_AUTH_PROFILE_KEY = "chatgpt_ms_auth_profile"
_SCOPE_STATE_MS_AUTH_ACCESS_TOKEN_KEY = "chatgpt_ms_auth_access_token"

INVENTORY_WIDGET_URI = "ui://widget/analyze-inventory.html"
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

_COMPANY_CHECKED_PLAN_TOOLS = {
    "get_improvement_plan_by_inventory",
    "get_improvement_plan_problem",
    "get_improvement_plan_method",
    "get_improvement_plan_reasoning",
}
