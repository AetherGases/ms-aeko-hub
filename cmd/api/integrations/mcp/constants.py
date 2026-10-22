"""MCP server configuration, tool names, and descriptions.

Load configuration from the repository environment file without overriding process settings.
"""

import json
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[4] / ".env", override=False)

DEFAULT_STARTUP_TIMEOUT = float(os.environ["DEFAULT_STARTUP_TIMEOUT"])

DEFAULT_CALL_TIMEOUT = float(os.environ["DEFAULT_CALL_TIMEOUT"])

DEFAULT_CLOSE_TIMEOUT = float(os.environ["DEFAULT_CLOSE_TIMEOUT"])

QUERY_GASES_INFO_TOOL_NAME = os.environ["QUERY_GASES_INFO_TOOL_NAME"]

CHROMA_MCP_SERVER_SCRIPT = (
    Path(__file__).parent / os.environ["CHROMA_MCP_SERVER_SCRIPT"]
)

PASSTHROUGH_ENV_VARS = tuple(json.loads(os.environ["PASSTHROUGH_ENV_VARS"]))

QUIET_CHILD_ENV = json.loads(os.environ["QUIET_CHILD_ENV"])

QUERY_GASES_INFO_DESCRIPTION = os.environ["QUERY_GASES_INFO_DESCRIPTION"]

GASES_INFO_COLLECTION = os.environ["GASES_INFO_COLLECTION"]

IMPROVEMENT_PLAN_PROBLEMS_COLLECTION = os.environ[
    "IMPROVEMENT_PLAN_PROBLEMS_COLLECTION"
]

QUERY_IMPROVEMENT_PLAN_PROBLEMS_TOOL_NAME = os.environ[
    "QUERY_IMPROVEMENT_PLAN_PROBLEMS_TOOL_NAME"
]

QUERY_IMPROVEMENT_PLAN_PROBLEMS_DESCRIPTION = os.environ[
    "QUERY_IMPROVEMENT_PLAN_PROBLEMS_DESCRIPTION"
]

EMBEDDING_MODEL = os.environ["EMBEDDING_MODEL"]

DEFAULT_RESULT_COUNT = int(os.environ["DEFAULT_RESULT_COUNT"])

QUERY_INCLUDE = json.loads(os.environ["QUERY_INCLUDE"])

TAVILY_SEARCH_DESCRIPTION = os.environ["TAVILY_SEARCH_DESCRIPTION"]

TAVILY_RESEARCH_DESCRIPTION = os.environ["TAVILY_RESEARCH_DESCRIPTION"]

TAVILY_MAP_DESCRIPTION = os.environ["TAVILY_MAP_DESCRIPTION"]
