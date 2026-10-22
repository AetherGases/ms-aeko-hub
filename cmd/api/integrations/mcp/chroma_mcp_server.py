"""Serve Chroma Cloud searches for gases-info and improvement-plan problems.

Queries use the corpus embedding model and cached collections. Warning-level
logging limits output to the MCP stderr pipe. Model imports run on the main
thread at startup before synchronous queries execute on worker threads.
"""

import os
import sys
from typing import Any

from chromadb import CloudClient
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
from mcp.server.fastmcp import FastMCP


if __package__:
    from .constants import (
        GASES_INFO_COLLECTION,
        IMPROVEMENT_PLAN_PROBLEMS_COLLECTION,
        EMBEDDING_MODEL,
        DEFAULT_RESULT_COUNT,
        QUERY_INCLUDE,
    )
else:
    from constants import (
        GASES_INFO_COLLECTION,
        IMPROVEMENT_PLAN_PROBLEMS_COLLECTION,
        EMBEDDING_MODEL,
        DEFAULT_RESULT_COUNT,
        QUERY_INCLUDE,
    )


mcp = FastMCP("aeko-chroma", log_level="WARNING")

_collection = None
_plan_collection = None


def _required_setting(env_var: str) -> str:
    """Resolve a required Chroma Cloud setting and reject an empty value."""

    value = os.environ.get(env_var, "")
    if value == "":
        raise RuntimeError(f"{env_var} is not set in the MCP server's environment.")

    return value


def _embedding_function() -> SentenceTransformerEmbeddingFunction:
    """Build the embedding function using the same model as the stored corpus."""

    return SentenceTransformerEmbeddingFunction(model_name=EMBEDDING_MODEL)


def _build_client() -> Any:
    """Build an authenticated Chroma Cloud client from required settings."""

    return CloudClient(
        tenant=_required_setting("CHROMA_TENANT"),
        database=_required_setting("CHROMA_DATABASE"),
        api_key=_required_setting("CHROMA_API_KEY"),
    )


def _get_collection() -> Any:
    """Resolve and cache the gases-info collection with its embedding function."""

    global _collection
    if _collection is None:
        _collection = _build_client().get_collection(
            GASES_INFO_COLLECTION,
            embedding_function=_embedding_function(),
        )

    return _collection


def _get_plan_collection() -> Any:
    """Resolve and cache the improvement-plan-problems collection."""

    global _plan_collection
    if _plan_collection is None:
        _plan_collection = _build_client().get_or_create_collection(
            IMPROVEMENT_PLAN_PROBLEMS_COLLECTION,
            embedding_function=_embedding_function(),
        )

    return _plan_collection


@mcp.tool()
def query_gases_info(
    query_texts: list[str],
    n_results: int = DEFAULT_RESULT_COUNT,
) -> dict:
    """Search the Aether greenhouse-gas knowledge base by meaning.

    Args:
        query_texts: The questions or topics to look up, in plain text.
        n_results: How many passages to return per query.
    """

    return _get_collection().query(
        query_texts=query_texts,
        n_results=n_results,
        include=QUERY_INCLUDE,
    )


@mcp.tool()
def query_improvement_plan_problems(
    query_texts: list[str],
    id_external_company: int,
    n_results: int = DEFAULT_RESULT_COUNT,
) -> dict:
    """Search indexed defined_problems belonging to one company."""

    return _get_plan_collection().query(
        query_texts=query_texts,
        n_results=n_results,
        where={"id_external_company": id_external_company},
        include=QUERY_INCLUDE,
    )


@mcp.tool()
def upsert_improvement_plan_problem(
    id_external_inventory: int,
    defined_problem: str,
    id_external_company: int,
) -> dict:
    """Index one plan's defined problem; id is the external inventory identifier."""

    _get_plan_collection().upsert(
        ids=[str(id_external_inventory)],
        documents=[defined_problem],
        metadatas=[
            {
                "id_external_inventory": id_external_inventory,
                "id_external_company": id_external_company,
            }
        ],
    )
    return {"id": str(id_external_inventory)}


def main() -> None:
    """Import the embedding model on the main thread, warm the collection, and serve MCP over stdio."""

    import sentence_transformers

    try:
        _get_collection()
    except Exception as exc:
        print(f"chroma warm-up failed: {type(exc).__name__}: {exc}", file=sys.stderr)

    try:
        _get_plan_collection()
    except Exception as exc:
        print(
            f"chroma plan-collection warm-up failed: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )

    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
