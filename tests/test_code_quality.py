"""Enforce documentation and comment standards across the API and its tests."""

import ast
import io
import tokenize
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SOURCES = sorted(
    path
    for directory in (
        "aeko_metrics",
        "cmd",
        "hub_metrics",
        "improvement_plan",
        "internal",
        "oauth",
        "session",
        "tests",
        "upload_ticket",
        "user",
    )
    for path in (ROOT / directory).rglob("*.py")
)


@pytest.mark.parametrize("path", SOURCES, ids=lambda path: str(path.relative_to(ROOT)))
def test_modules_describe_their_purpose(path):
    """Require a module docstring in every Python source file."""
    assert ast.get_docstring(ast.parse(path.read_text(encoding="utf-8-sig")))


@pytest.mark.parametrize("path", SOURCES, ids=lambda path: str(path.relative_to(ROOT)))
def test_public_functions_describe_their_purpose(path):
    """Require docstrings on public functions, including methods and callbacks."""
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    missing = [
        f"{node.name}:{node.lineno}"
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and not node.name.startswith("_")
        and not ast.get_docstring(node)
    ]
    assert not missing, f"Missing function docstrings: {', '.join(missing)}"


@pytest.mark.parametrize("path", SOURCES, ids=lambda path: str(path.relative_to(ROOT)))
def test_python_sources_have_no_comments(path):
    """Reject comment tokens without treating hashes inside strings as comments."""
    source = path.read_text(encoding="utf-8-sig")
    comments = [
        token.start[0]
        for token in tokenize.generate_tokens(io.StringIO(source).readline)
        if token.type == tokenize.COMMENT
    ]
    assert not comments, f"Comments on lines: {comments}"
