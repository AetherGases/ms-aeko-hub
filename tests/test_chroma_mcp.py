"""Verify chroma mcp behavior and error handling."""

import sys

import pytest
from langchain_core.tools import Tool

from cmd.api.integrations.mcp import chroma_mcp
from cmd.api.integrations.mcp import mcp_session

CLOUD_ENV = {
    "CHROMA_TENANT": "tenant-from-env",
    "CHROMA_DATABASE": "aeko-gases-vector-store",
    "CHROMA_API_KEY": "key-from-env",
}


class FakeMCPTool:
    """Stands in for a tool the MCP session would expose."""

    def __init__(self, name, result=None):
        self.name = name
        self.description = f"fake {name}"
        self.result = result
        self.calls = []

    async def ainvoke(self, kwargs):
        """Record an asynchronous tool invocation and return its scripted response."""
        self.calls.append(kwargs)
        return self.result


class FakeMCPSession:
    """The `ClientSession` the persistent session opens once and reuses."""

    def __init__(self, tools):
        self.tools = tools


class FakeSessionContext:
    """`MultiServerMCPClient.session()` is an async context manager."""

    def __init__(self, tools):
        self.session = FakeMCPSession(tools)
        self.exited = False

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, *exc_info):
        self.exited = True
        return False


class FakeMCPClient:
    """Simulate a persistent MultiServerMCPClient session."""

    def __init__(self, tools):
        self._tools = tools
        self.server_name = None
        self.contexts = []

    def session(self, server_name):
        """Provide a simulated MCP session context."""
        self.server_name = server_name
        context = FakeSessionContext(self._tools)
        self.contexts.append(context)
        return context


class RecordingMultiServerMCPClient:
    """Stands in for `langchain_mcp_adapters`' client, recording its config."""

    instances = []

    def __init__(self, config):
        self.config = config
        RecordingMultiServerMCPClient.instances.append(self)


@pytest.fixture(autouse=True)
def reset_recorder():
    """Reset the MCP call recorder before each test."""
    RecordingMultiServerMCPClient.instances = []
    yield


@pytest.fixture(autouse=True)
def fresh_mcp_session(monkeypatch):
    """Replace the shared MCP session with an isolated session for the test."""

    async def load_tools(session, **kwargs):
        """Return scripted tools for MCP session discovery."""
        return session.tools

    monkeypatch.setattr(mcp_session, "load_mcp_tools", load_tools)
    chroma_mcp.CHROMA_SESSION.close()
    yield
    chroma_mcp.CHROMA_SESSION.close()


@pytest.fixture(autouse=True)
def reset_plan_services():
    """Clear user and plan services bound for the agent wrapper."""
    chroma_mcp.configure()
    yield
    chroma_mcp.configure()


@pytest.fixture
def cloud_env(monkeypatch):
    """Set Chroma Cloud credentials for the test."""
    for name, value in CLOUD_ENV.items():
        monkeypatch.setenv(name, value)
    return CLOUD_ENV


def configured_child(monkeypatch, *args):
    """Build the configured Chroma child process settings."""
    monkeypatch.setattr(
        chroma_mcp, "MultiServerMCPClient", RecordingMultiServerMCPClient
    )
    chroma_mcp._configure_mcp_client(*args)
    return RecordingMultiServerMCPClient.instances[-1].config["chroma"]


def test_configure_mcp_client_spawns_the_projects_own_server_over_stdio(monkeypatch):
    """Verify that configure mcp client spawns the projects own server over stdio."""
    config = configured_child(
        monkeypatch, "explicit-tenant", "explicit-database", "explicit-key"
    )

    assert config["transport"] == "stdio"
    assert config["command"] == sys.executable
    assert config["args"] == [str(chroma_mcp.CHROMA_MCP_SERVER_SCRIPT)]


def test_the_configured_server_script_actually_exists():
    """Verify that the configured server script actually exists."""
    assert chroma_mcp.CHROMA_MCP_SERVER_SCRIPT.is_file()


def test_configure_mcp_client_hands_the_credentials_to_the_child_environment(
    monkeypatch,
):
    """Verify that configure mcp client hands the credentials to the child environment."""
    config = configured_child(
        monkeypatch, "explicit-tenant", "explicit-database", "explicit-key"
    )

    assert config["env"]["CHROMA_TENANT"] == "explicit-tenant"
    assert config["env"]["CHROMA_DATABASE"] == "explicit-database"
    assert config["env"]["CHROMA_API_KEY"] == "explicit-key"


def test_configure_mcp_client_keeps_the_api_key_out_of_argv(monkeypatch):
    """Verify that configure mcp client keeps the api key out of argv."""
    config = configured_child(
        monkeypatch, "explicit-tenant", "explicit-database", "explicit-key"
    )

    assert "explicit-key" not in config["args"]


def test_configure_mcp_client_passes_the_model_cache_location_through(monkeypatch):
    """Verify that configure mcp client passes the model cache location through."""
    monkeypatch.setenv("HF_HOME", "/models/hf")
    monkeypatch.setenv("PATH", "/usr/local/bin:/usr/bin")

    config = configured_child(
        monkeypatch, "explicit-tenant", "explicit-database", "explicit-key"
    )

    assert config["env"]["HF_HOME"] == "/models/hf"
    assert config["env"]["PATH"] == "/usr/local/bin:/usr/bin"


def test_configure_mcp_client_omits_passthrough_variables_that_are_unset(monkeypatch):
    """Verify that configure mcp client omits passthrough variables that are unset."""
    monkeypatch.delenv("SENTENCE_TRANSFORMERS_HOME", raising=False)

    config = configured_child(
        monkeypatch, "explicit-tenant", "explicit-database", "explicit-key"
    )

    assert "SENTENCE_TRANSFORMERS_HOME" not in config["env"]


def test_configure_mcp_client_forwards_server_configuration(monkeypatch):
    """Pass environment overrides to the child without relying on a deployed dotenv file."""
    monkeypatch.setenv("EMBEDDING_MODEL", "configured-embedding-model")
    monkeypatch.setenv("DEFAULT_RESULT_COUNT", "3")
    monkeypatch.setenv("QUERY_INCLUDE", '["documents"]')
    config = configured_child(
        monkeypatch, "explicit-tenant", "explicit-database", "explicit-key"
    )
    assert config["env"]["EMBEDDING_MODEL"] == "configured-embedding-model"
    assert config["env"]["DEFAULT_RESULT_COUNT"] == "3"
    assert config["env"]["QUERY_INCLUDE"] == '["documents"]'


def test_configure_mcp_client_falls_back_to_the_chroma_env_vars(monkeypatch, cloud_env):
    """Verify that configure mcp client falls back to the chroma env vars."""
    config = configured_child(monkeypatch)

    assert config["env"]["CHROMA_TENANT"] == "tenant-from-env"
    assert config["env"]["CHROMA_DATABASE"] == "aeko-gases-vector-store"
    assert config["env"]["CHROMA_API_KEY"] == "key-from-env"


@pytest.mark.parametrize(
    "missing", ["CHROMA_TENANT", "CHROMA_DATABASE", "CHROMA_API_KEY"]
)
def test_configure_mcp_client_raises_naming_the_missing_variable(
    monkeypatch, cloud_env, missing
):
    """Verify that configure mcp client raises naming the missing variable."""
    monkeypatch.setattr(
        chroma_mcp, "MultiServerMCPClient", RecordingMultiServerMCPClient
    )
    monkeypatch.delenv(missing, raising=False)

    with pytest.raises(RuntimeError, match=missing):
        chroma_mcp._configure_mcp_client()


def test_query_gases_info_invokes_the_servers_query_tool_with_the_search_text(
    monkeypatch,
):
    """Verify that query gases info invokes the servers query tool with the search text."""
    query_tool = FakeMCPTool(
        "query_gases_info", result={"documents": [["metano pode virar biogas"]]}
    )
    monkeypatch.setattr(
        chroma_mcp, "_configure_mcp_client", lambda: FakeMCPClient([query_tool])
    )

    result = chroma_mcp._query_gases_info("substituto para o metano")

    assert result == {"documents": [["metano pode virar biogas"]]}
    assert query_tool.calls == [{"query_texts": ["substituto para o metano"]}]


def test_query_gases_info_never_lets_the_agent_name_a_collection(monkeypatch):
    """Verify that query gases info never lets the agent name a collection."""
    query_tool = FakeMCPTool("query_gases_info", result={})
    monkeypatch.setattr(
        chroma_mcp, "_configure_mcp_client", lambda: FakeMCPClient([query_tool])
    )

    chroma_mcp._query_gases_info("qualquer coisa")

    assert set(query_tool.calls[-1]) == {"query_texts"}


def test_query_gases_info_raises_a_clear_error_when_the_server_has_no_query_tool(
    monkeypatch,
):
    """Verify that query gases info raises a clear error when the server has no query tool."""
    other_tool = FakeMCPTool("something_else")
    monkeypatch.setattr(
        chroma_mcp, "_configure_mcp_client", lambda: FakeMCPClient([other_tool])
    )

    with pytest.raises(LookupError, match="query_gases_info"):
        chroma_mcp._query_gases_info("qualquer coisa")


def test_query_gases_info_never_reaches_the_server_with_an_empty_query(monkeypatch):
    """Verify that query gases info never reaches the server with an empty query."""
    query_tool = FakeMCPTool("query_gases_info", result={})
    monkeypatch.setattr(
        chroma_mcp, "_configure_mcp_client", lambda: FakeMCPClient([query_tool])
    )

    with pytest.raises(ValueError, match="non-empty"):
        chroma_mcp._query_gases_info("   ")

    assert query_tool.calls == []


def test_parse_query_wraps_a_single_string():
    """Verify that parse query wraps a single string."""
    assert chroma_mcp._parse_query("gases de efeito estufa") == [
        "gases de efeito estufa"
    ]


def test_parse_query_passes_a_list_of_strings_through():
    """Verify that parse query passes a list of strings through."""
    assert chroma_mcp._parse_query(["metano", "CO2"]) == ["metano", "CO2"]


def test_parse_query_drops_surrounding_whitespace():
    """Verify that parse query drops surrounding whitespace."""
    assert chroma_mcp._parse_query("  metano  ") == ["metano"]


@pytest.mark.parametrize("empty", [None, "", "   ", [], ["  "]])
def test_parse_query_rejects_empty_input(empty):
    """Verify that parse query rejects empty input."""
    with pytest.raises(ValueError, match="non-empty"):
        chroma_mcp._parse_query(empty)


@pytest.mark.parametrize("bad", [42, {"query": "metano"}, ["metano", 7]])
def test_parse_query_rejects_anything_that_is_not_text(bad):
    """Verify that parse query rejects anything that is not text."""
    with pytest.raises(ValueError, match="non-empty"):
        chroma_mcp._parse_query(bad)


def test_get_gases_info_tools_returns_a_single_query_tool():
    """Verify that get gases info tools returns a single query tool."""
    tools = chroma_mcp.get_gases_info_tools()

    assert len(tools) == 1
    assert isinstance(tools[0], Tool)
    assert tools[0].name == "query_gases_info"
    assert tools[0].description


def test_get_gases_info_tools_entry_is_backed_by_query_gases_info(monkeypatch):
    """Verify that get gases info tools entry is backed by query gases info."""
    query_tool = FakeMCPTool("query_gases_info", result="gases info results")
    monkeypatch.setattr(
        chroma_mcp, "_configure_mcp_client", lambda: FakeMCPClient([query_tool])
    )

    tool = chroma_mcp.get_gases_info_tools()[0]

    assert tool.func("trocas possiveis para o SF6") == "gases info results"
    assert query_tool.calls[-1] == {"query_texts": ["trocas possiveis para o SF6"]}


class StubUser:
    """User row the wrapper reads for company scope."""

    def __init__(self, id_external_company=90):
        self.id = "u1"
        self.id_external_user = 12345
        self.id_external_company = id_external_company


class StubUserService:
    """Records external-user lookups and returns a scripted user."""

    def __init__(self, user=None, error=None):
        self.user = user or StubUser()
        self.error = error
        self.calls = []

    def get_mongo_user(self, identifier):
        """Return the scripted user or raise the scripted error."""
        self.calls.append(("get_mongo_user", identifier))
        if self.error is not None:
            raise self.error
        return self.user


class StubPlan:
    """Improvement plan the wrapper hydrates from Mongo."""

    def __init__(self, company=90, inventory=502):
        self.id = "p1"
        self.id_external_inventory = inventory
        self.id_external_company = company
        self.defined_problem = "flaring"
        self.method = "PDCA"
        self.reasoning = "replace the flare"
        self.updated_at = "2026-07-26T14:30:00Z"


class StubPlanService:
    """Records inventory lookups and returns a scripted plan."""

    def __init__(self, plan=None, error=None):
        self.plan = plan or StubPlan()
        self.error = error
        self.calls = []

    def get_by_id_external_inventory(self, identifier):
        """Return the scripted plan or raise the scripted error."""
        self.calls.append(("get_by_id_external_inventory", identifier))
        if self.error is not None:
            raise self.error
        return self.plan


PLAN_QUERY_RESULT = {
    "metadatas": [[{"id_external_inventory": 502, "id_external_company": 90}]],
    "documents": [["flaring"]],
}

CATALOG_PLAN = {
    "id_external_inventory": 502,
    "defined_problem": "flaring",
    "method": "PDCA",
    "reasoning": "replace the flare",
    "updated_at": "2026-07-26T14:30:00Z",
}


def bind_plan_query(
    monkeypatch, result=None, tool_name="query_improvement_plan_problems"
):
    """Point the Chroma session at one scripted MCP tool."""
    tool = FakeMCPTool(
        tool_name, result=result if result is not None else PLAN_QUERY_RESULT
    )
    monkeypatch.setattr(
        chroma_mcp, "_configure_mcp_client", lambda: FakeMCPClient([tool])
    )
    return tool


def test_query_improvement_plan_problems_injects_the_users_company_and_hides_where(
    monkeypatch,
):
    """Verify that query improvement plan problems injects the users company and hides where."""
    query_tool = bind_plan_query(monkeypatch)
    chroma_mcp.configure(users=StubUserService(), improvement_plans=StubPlanService())

    result = chroma_mcp._query_improvement_plan_problems(12345, "flaring")

    assert query_tool.calls == [{"query_texts": ["flaring"], "id_external_company": 90}]
    assert result == [CATALOG_PLAN]
    assert "id_external_company" not in result[0]


def test_query_improvement_plan_problems_never_lets_the_agent_name_a_collection():
    """Verify that query improvement plan problems never lets the agent name a collection."""
    tool = chroma_mcp.get_improvement_plan_problem_tools()[0]

    assert set(tool.args) == {"id_external_user", "query"}


def test_query_improvement_plan_problems_drops_a_plan_from_another_company(monkeypatch):
    """Verify that query improvement plan problems drops a plan from another company."""
    bind_plan_query(monkeypatch)
    chroma_mcp.configure(
        users=StubUserService(),
        improvement_plans=StubPlanService(plan=StubPlan(company=91)),
    )

    assert chroma_mcp._query_improvement_plan_problems(12345, "flaring") == []


def test_query_improvement_plan_problems_drops_a_missing_mongo_plan(monkeypatch):
    """Verify that query improvement plan problems drops a missing mongo plan."""
    bind_plan_query(monkeypatch)
    chroma_mcp.configure(
        users=StubUserService(),
        improvement_plans=StubPlanService(error=ValueError("missing plan")),
    )

    assert chroma_mcp._query_improvement_plan_problems(12345, "flaring") == []


def test_query_improvement_plan_problems_rejects_empty_query(monkeypatch):
    """Verify that query improvement plan problems rejects empty query."""
    query_tool = bind_plan_query(monkeypatch)
    chroma_mcp.configure(users=StubUserService(), improvement_plans=StubPlanService())

    with pytest.raises(ValueError):
        chroma_mcp._query_improvement_plan_problems(12345, "   ")

    assert query_tool.calls == []


def test_query_improvement_plan_problems_rejects_an_unusable_user_id(monkeypatch):
    """Verify that query improvement plan problems rejects an unusable user id."""
    bind_plan_query(monkeypatch)
    users = StubUserService()
    chroma_mcp.configure(users=users, improvement_plans=StubPlanService())

    for bad_id in (True, 0):
        with pytest.raises(ValueError):
            chroma_mcp._query_improvement_plan_problems(bad_id, "flaring")

    assert users.calls == []


def test_query_improvement_plan_problems_rejects_a_user_without_company(monkeypatch):
    """Verify that query improvement plan problems rejects a user without company."""
    query_tool = bind_plan_query(monkeypatch)
    chroma_mcp.configure(
        users=StubUserService(user=StubUser(id_external_company=None)),
        improvement_plans=StubPlanService(),
    )

    with pytest.raises(ValueError, match="id_external_company"):
        chroma_mcp._query_improvement_plan_problems(12345, "flaring")

    assert query_tool.calls == []


def test_query_improvement_plan_problems_raises_when_the_mcp_tool_is_missing(
    monkeypatch,
):
    """Verify that query improvement plan problems raises when the mcp tool is missing."""
    bind_plan_query(monkeypatch, tool_name="query_gases_info")
    chroma_mcp.configure(users=StubUserService(), improvement_plans=StubPlanService())

    with pytest.raises(LookupError, match="query_improvement_plan_problems"):
        chroma_mcp._query_improvement_plan_problems(12345, "flaring")


def test_upsert_improvement_plan_problem_calls_mcp(monkeypatch):
    """Verify that upsert improvement plan problem calls mcp."""
    upsert_tool = FakeMCPTool("upsert_improvement_plan_problem", result={"id": "502"})
    monkeypatch.setattr(
        chroma_mcp, "_configure_mcp_client", lambda: FakeMCPClient([upsert_tool])
    )

    chroma_mcp._upsert_improvement_plan_problem(502, "flaring", 90)

    assert upsert_tool.calls == [
        {
            "id_external_inventory": 502,
            "defined_problem": "flaring",
            "id_external_company": 90,
        }
    ]


def test_get_improvement_plan_problem_tools_does_not_expose_upsert():
    """Verify that get improvement plan problem tools does not expose upsert."""
    names = {tool.name for tool in chroma_mcp.get_improvement_plan_problem_tools()}

    assert names == {"query_improvement_plan_problems"}
