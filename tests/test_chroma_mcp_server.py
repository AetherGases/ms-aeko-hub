"""Verify chroma mcp server behavior and error handling."""

import asyncio
import inspect
import runpy
import sys
import types
from pathlib import Path

import pytest

from cmd.api.integrations.mcp import chroma_mcp_server
from cmd.api.integrations.mcp import constants


def test_standalone_server_loads_package_constants(monkeypatch):
    """Load the server by file path with no package context or external server startup."""
    script = Path(chroma_mcp_server.__file__)
    monkeypatch.syspath_prepend(str(script.parent))
    monkeypatch.delitem(sys.modules, "constants", raising=False)
    try:
        namespace = runpy.run_path(str(script))
        assert not namespace["__package__"]
        assert namespace["GASES_INFO_COLLECTION"] == constants.GASES_INFO_COLLECTION
        assert (
            namespace["IMPROVEMENT_PLAN_PROBLEMS_COLLECTION"]
            == constants.IMPROVEMENT_PLAN_PROBLEMS_COLLECTION
        )
        assert namespace["EMBEDDING_MODEL"] == constants.EMBEDDING_MODEL
        assert namespace["DEFAULT_RESULT_COUNT"] == constants.DEFAULT_RESULT_COUNT
        assert namespace["QUERY_INCLUDE"] == constants.QUERY_INCLUDE
    finally:
        sys.modules.pop("constants", None)


CLOUD_ENV = {
    "CHROMA_TENANT": "tenant-from-env",
    "CHROMA_DATABASE": "aeko-gases-vector-store",
    "CHROMA_API_KEY": "key-from-env",
}


class FakeCollection:
    def __init__(self, result=None):
        self.result = result if result is not None else {"documents": [[]]}
        self.queries = []
        self.upserts = []

    def query(self, **kwargs):
        """Record a vector query and return scripted search results."""
        self.queries.append(kwargs)
        return self.result

    def upsert(self, **kwargs):
        """Record an upsert of embedded plan problems."""
        self.upserts.append(kwargs)


class FakeClient:
    def __init__(self, collection=None):
        self.collection = collection or FakeCollection()
        self.get_collection_calls = []
        self.get_or_create_collection_calls = []

    def get_collection(self, name, embedding_function=None):
        """Record the collection lookup and return the test collection."""
        self.get_collection_calls.append((name, embedding_function))
        return self.collection

    def get_or_create_collection(self, name, embedding_function=None):
        """Record get-or-create and return the test collection."""
        self.get_or_create_collection_calls.append((name, embedding_function))
        return self.collection


class RecordingCloudClient:
    """Stands in for `chromadb.CloudClient`, recording how it was built."""

    instances = []

    def __init__(self, tenant=None, database=None, api_key=None):
        self.tenant = tenant
        self.database = database
        self.api_key = api_key
        self.collection = FakeCollection()
        RecordingCloudClient.instances.append(self)

    def get_collection(self, name, embedding_function=None):
        """Record the collection lookup and return the test collection."""
        return self.collection


class RecordingEmbeddingFunction:
    """Stands in for the sentence-transformer EF, which would load a model."""

    instances = []

    def __init__(self, model_name=None):
        self.model_name = model_name
        RecordingEmbeddingFunction.instances.append(self)


@pytest.fixture(autouse=True)
def reset_server_state(monkeypatch):
    """Clear cached Chroma server state for an isolated test."""
    RecordingCloudClient.instances = []
    RecordingEmbeddingFunction.instances = []
    monkeypatch.setattr(chroma_mcp_server, "_collection", None)
    monkeypatch.setattr(chroma_mcp_server, "_plan_collection", None)
    yield


@pytest.fixture
def cloud_env(monkeypatch):
    """Set Chroma Cloud credentials for the test."""
    for name, value in CLOUD_ENV.items():
        monkeypatch.setenv(name, value)
    return CLOUD_ENV


def test_build_client_uses_the_cloud_client_with_the_environments_credentials(
    monkeypatch, cloud_env
):
    """Verify that build client uses the cloud client with the environments credentials."""
    monkeypatch.setattr(chroma_mcp_server, "CloudClient", RecordingCloudClient)

    chroma_mcp_server._build_client()

    client = RecordingCloudClient.instances[-1]
    assert client.tenant == "tenant-from-env"
    assert client.database == "aeko-gases-vector-store"
    assert client.api_key == "key-from-env"


@pytest.mark.parametrize(
    "missing", ["CHROMA_TENANT", "CHROMA_DATABASE", "CHROMA_API_KEY"]
)
def test_build_client_raises_naming_the_missing_variable(
    monkeypatch, cloud_env, missing
):
    """Verify that build client raises naming the missing variable."""
    monkeypatch.setattr(chroma_mcp_server, "CloudClient", RecordingCloudClient)
    monkeypatch.delenv(missing, raising=False)

    with pytest.raises(RuntimeError, match=missing):
        chroma_mcp_server._build_client()


def test_the_embedding_function_is_the_model_the_corpus_was_ingested_with(monkeypatch):
    """Verify that the embedding function is the model the corpus was ingested with."""
    monkeypatch.setattr(
        chroma_mcp_server,
        "SentenceTransformerEmbeddingFunction",
        RecordingEmbeddingFunction,
    )

    chroma_mcp_server._embedding_function()

    assert RecordingEmbeddingFunction.instances[-1].model_name == (
        "paraphrase-multilingual-mpnet-base-v2"
    )


def test_get_collection_pins_the_gases_info_collection_and_the_embedding_function(
    monkeypatch,
):
    """Verify that get collection pins the gases info collection and the embedding function."""
    client = FakeClient()
    embedding_function = object()
    monkeypatch.setattr(chroma_mcp_server, "_build_client", lambda: client)
    monkeypatch.setattr(
        chroma_mcp_server, "_embedding_function", lambda: embedding_function
    )

    chroma_mcp_server._get_collection()

    assert client.get_collection_calls == [("gases-info", embedding_function)]


def test_get_plan_collection_pins_the_problems_collection(monkeypatch):
    """Verify that get plan collection pins the problems collection."""
    client = FakeClient()
    embedding_function = object()
    monkeypatch.setattr(chroma_mcp_server, "_build_client", lambda: client)
    monkeypatch.setattr(
        chroma_mcp_server, "_embedding_function", lambda: embedding_function
    )

    chroma_mcp_server._get_plan_collection()

    assert client.get_or_create_collection_calls == [
        ("improvement-plan-problems", embedding_function)
    ]


def test_get_collection_is_resolved_once_per_process(monkeypatch):
    """Verify that get collection is resolved once per process."""
    builds = []
    client = FakeClient()
    monkeypatch.setattr(
        chroma_mcp_server, "_build_client", lambda: builds.append(1) or client
    )
    monkeypatch.setattr(chroma_mcp_server, "_embedding_function", lambda: object())

    first = chroma_mcp_server._get_collection()
    second = chroma_mcp_server._get_collection()

    assert first is second
    assert builds == [1]


def query(**kwargs):
    """Record a vector query and return scripted search results."""

    result = chroma_mcp_server.query_gases_info(**kwargs)
    return asyncio.run(result) if inspect.isawaitable(result) else result


def invoke(function, /, *args, **kwargs):
    """Run an MCP tool, awaiting it when FastMCP returns a coroutine."""

    result = function(*args, **kwargs)
    return asyncio.run(result) if inspect.isawaitable(result) else result


def test_query_improvement_plan_problems_filters_by_company(monkeypatch):
    """Verify that query improvement plan problems filters by company."""
    collection = FakeCollection()
    monkeypatch.setattr(chroma_mcp_server, "_get_plan_collection", lambda: collection)

    invoke(
        chroma_mcp_server.query_improvement_plan_problems,
        query_texts=["flaring"],
        id_external_company=90,
    )

    recorded = collection.queries[-1]
    assert recorded["query_texts"] == ["flaring"]
    assert recorded["where"] == {"id_external_company": 90}
    assert recorded["n_results"] == 5
    assert "embeddings" not in recorded["include"]


def test_upsert_improvement_plan_problem_uses_inventory_id(monkeypatch):
    """Verify that upsert improvement plan problem uses inventory id."""
    collection = FakeCollection()
    monkeypatch.setattr(chroma_mcp_server, "_get_plan_collection", lambda: collection)

    result = invoke(
        chroma_mcp_server.upsert_improvement_plan_problem,
        502,
        "flaring at the stack",
        90,
    )

    assert result == {"id": "502"}
    assert collection.upserts[-1] == {
        "ids": ["502"],
        "documents": ["flaring at the stack"],
        "metadatas": [{"id_external_inventory": 502, "id_external_company": 90}],
    }


def test_query_gases_info_searches_the_pinned_collection(monkeypatch):
    """Verify that query gases info searches the pinned collection."""
    collection = FakeCollection(
        result={"documents": [["biogas substitui gas natural"]]}
    )
    monkeypatch.setattr(chroma_mcp_server, "_get_collection", lambda: collection)

    result = query(query_texts=["substituto para o metano"])

    assert result == {"documents": [["biogas substitui gas natural"]]}
    assert collection.queries[-1]["query_texts"] == ["substituto para o metano"]


def test_query_gases_info_defaults_the_result_count(monkeypatch):
    """Verify that query gases info defaults the result count."""
    collection = FakeCollection()
    monkeypatch.setattr(chroma_mcp_server, "_get_collection", lambda: collection)

    query(query_texts=["metano"])

    assert collection.queries[-1]["n_results"] == 5


def test_query_gases_info_honours_an_explicit_result_count(monkeypatch):
    """Verify that query gases info honours an explicit result count."""
    collection = FakeCollection()
    monkeypatch.setattr(chroma_mcp_server, "_get_collection", lambda: collection)

    query(query_texts=["metano"], n_results=12)

    assert collection.queries[-1]["n_results"] == 12


def test_query_gases_info_returns_text_and_never_raw_vectors(monkeypatch):
    """Verify that query gases info returns text and never raw vectors."""
    collection = FakeCollection()
    monkeypatch.setattr(chroma_mcp_server, "_get_collection", lambda: collection)

    query(query_texts=["metano"])

    included = collection.queries[-1]["include"]
    assert "documents" in included
    assert "embeddings" not in included


@pytest.fixture
def started_server(monkeypatch):
    """Start the Chroma server with external dependencies replaced."""

    monkeypatch.setitem(
        sys.modules, "sentence_transformers", types.ModuleType("sentence_transformers")
    )

    transports = []
    monkeypatch.setattr(
        chroma_mcp_server.mcp, "run", lambda transport: transports.append(transport)
    )
    return transports


def test_main_serves_over_stdio(monkeypatch, started_server):
    """Verify that main serves over stdio."""
    monkeypatch.setattr(chroma_mcp_server, "_get_collection", lambda: FakeCollection())
    monkeypatch.setattr(
        chroma_mcp_server, "_get_plan_collection", lambda: FakeCollection()
    )

    chroma_mcp_server.main()

    assert started_server == ["stdio"]


def test_main_warms_the_collection_up_before_serving(monkeypatch, started_server):
    """Verify that main warms the gases and plan collections before serving."""
    warmed = []
    warmed_plan = []

    def warm_gases():
        """Record the gases warm-up and confirm the server has not started."""
        assert started_server == []
        warmed.append(1)
        return FakeCollection()

    def warm_plan():
        """Record the plan warm-up and confirm the server has not started."""
        assert started_server == []
        warmed_plan.append(1)
        return FakeCollection()

    monkeypatch.setattr(chroma_mcp_server, "_get_collection", warm_gases)
    monkeypatch.setattr(chroma_mcp_server, "_get_plan_collection", warm_plan)

    chroma_mcp_server.main()

    assert warmed == [1]
    assert warmed_plan == [1]
    assert started_server == ["stdio"]


@pytest.mark.parametrize("failing_getter", ["_get_collection", "_get_plan_collection"])
def test_main_still_serves_when_the_warm_up_fails(
    monkeypatch, started_server, failing_getter
):
    """Verify that main still serves when either collection warm-up fails."""

    def explode():
        """Raise the configured failure to exercise error handling."""
        raise RuntimeError("CHROMA_API_KEY is not set in the MCP server's environment.")

    monkeypatch.setattr(chroma_mcp_server, "_get_collection", lambda: FakeCollection())
    monkeypatch.setattr(
        chroma_mcp_server, "_get_plan_collection", lambda: FakeCollection()
    )
    monkeypatch.setattr(chroma_mcp_server, failing_getter, explode)

    chroma_mcp_server.main()

    assert started_server == ["stdio"]
