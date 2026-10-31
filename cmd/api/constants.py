"""Application composition settings loaded from the repository environment."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)

MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = os.getenv("DB_NAME")
REDIS_URI = os.getenv("REDIS_URI")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
AEKO_FAST_MODEL = os.getenv("AEKO_FAST_MODEL")
AEKO_SLOW_MODEL = os.getenv("AEKO_SLOW_MODEL")
AEKO_MAX_TOKENS = os.getenv("AEKO_MAX_TOKENS")
AEKO_REPORT_MAX_TOKENS = os.getenv("AEKO_REPORT_MAX_TOKENS")
AEKO_TEMPERATURE = os.getenv("AEKO_TEMPERATURE")
AEKO_TOP_P = os.getenv("AEKO_TOP_P")
AEKO_TOP_K = os.getenv("AEKO_TOP_K")
AEKO_WRITE_FAILURE_MESSAGE = os.getenv("AEKO_WRITE_FAILURE_MESSAGE")

CHATGPT_MCP_PREFIX = "/ai/mcp"

MCP_WARM_UP = os.getenv("AEKO_MCP_WARM_UP", "true")

OPENAPI_TAGS = [
    {
        "name": "Users",
        "description": "Endpoints for retrieving user profile data used by the AI gateway.",
    },
    {
        "name": "Sessions",
        "description": "Endpoints for listing sessions and session messages.",
    },
    {
        "name": "Reports",
        "description": "Endpoints for analyzing inventories and reading the stored textual improvement plan.",
    },
]
