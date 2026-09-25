"""Verify that packages centralize configuration constants without runtime dependencies."""

import ast
import runpy
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "package",
    [
        "internal/shared",
        "cmd/api/tools",
        "cmd/api/integrations/mcp",
        "cmd/memory_generator_worker",
        "improvement_plan",
    ],
)
def test_package_constants_have_one_definition_module(package):
    """Require package constants to be defined centrally, excluding live MCP sessions."""
    directory = Path(__file__).resolve().parents[1] / package
    assert (directory / "constants.py").is_file()
    misplaced = []
    for path in directory.glob("*.py"):
        if path.name == "constants.py":
            continue
        for node in ast.parse(path.read_text(encoding="utf-8")).body:
            targets = (
                node.targets if isinstance(node, ast.Assign)
                else [node.target] if isinstance(node, ast.AnnAssign)
                else []
            )
            for target in targets:
                if isinstance(target, ast.Name) and target.id.isupper():
                    if target.id in {"CHROMA_SESSION", "MONGO_SESSION", "TAVILY_SESSION"}:
                        continue
                    misplaced.append(f"{path.name}:{target.id}")
    assert not misplaced, misplaced


@pytest.mark.parametrize(
    "package, key, value, expected",
    [
        ("internal/shared", "APP_NAME", "custom-hub", "custom-hub"),
        ("internal/shared", "FAILING_STATUS", "499", 499),
        ("cmd/api/tools", "CALCULATOR_MAX_EXPRESSION_LENGTH", "200", 200),
        ("cmd/api/integrations/mcp", "DEFAULT_CALL_TIMEOUT", "17.5", 17.5),
        ("cmd/memory_generator_worker", "SESSION_INACTIVITY_MINUTES", "30", 30),
    ],
)
def test_constants_use_environment_overrides(monkeypatch, package, key, value, expected):
    """Honor environment settings and convert numeric configuration to its runtime type."""
    monkeypatch.setenv(key, value)
    path = Path(__file__).resolve().parents[1] / package / "constants.py"
    assert runpy.run_path(str(path))[key] == expected


def test_finance_descriptions_follow_configured_horizon(monkeypatch):
    """Keep the tool prompt consistent with the configured investment horizon."""
    monkeypatch.setenv("ROI_HORIZON_MONTHS", "24")
    path = Path(__file__).resolve().parents[1] / "cmd/api/tools/constants.py"
    values = runpy.run_path(str(path))
    assert values["ROI_HORIZON_MONTHS"] == 24
    assert "24-month horizon" in values["ROI_DESCRIPTION"]


@pytest.mark.parametrize(
    "package, key, value, expected",
    [
        ("internal/shared", "TRUE_VALUES", '["enabled", "yes"]', {"enabled", "yes"}),
        ("internal/shared", "BLUE", '"\\u001b[36m"', "\033[36m"),
        ("internal/shared", "INDENT", "  ", "  "),
        ("cmd/api/integrations/mcp", "QUERY_INCLUDE", '["documents"]', ["documents"]),
        ("cmd/api/integrations/mcp", "QUIET_CHILD_ENV", '{"TQDM_DISABLE": "1"}', {"TQDM_DISABLE": "1"}),
    ],
)
def test_constants_decode_structured_configuration(monkeypatch, package, key, value, expected):
    """Decode JSON settings while retaining collection types, ANSI escapes, and whitespace."""
    monkeypatch.setenv(key, value)
    path = Path(__file__).resolve().parents[1] / package / "constants.py"
    assert runpy.run_path(str(path))[key] == expected


def test_missing_configuration_has_no_hardcoded_fallback(monkeypatch):
    """Report a missing configuration key when neither the environment nor a file supplies it."""
    monkeypatch.delenv("SESSION_INACTIVITY_MINUTES", raising=False)
    monkeypatch.setattr("dotenv.load_dotenv", lambda *args, **kwargs: False)
    path = Path(__file__).resolve().parents[1] / "cmd/memory_generator_worker/constants.py"
    with pytest.raises(KeyError, match="SESSION_INACTIVITY_MINUTES"):
        runpy.run_path(str(path))


def test_configuration_loads_from_env_file_outside_working_directory(monkeypatch, tmp_path):
    """Find the repository configuration independently of the launch directory."""
    root = Path(__file__).resolve().parents[1]
    package = tmp_path / "cmd" / "memory_generator_worker"
    package.mkdir(parents=True)
    script = package / "constants.py"
    script.write_text(
        (root / "cmd/memory_generator_worker/constants.py").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (tmp_path / ".env").write_text("SESSION_INACTIVITY_MINUTES=7\n", encoding="utf-8")
    launch = tmp_path / "launch"
    launch.mkdir()
    monkeypatch.delenv("SESSION_INACTIVITY_MINUTES", raising=False)
    monkeypatch.chdir(launch)
    values = runpy.run_path(str(script))
    assert values["SESSION_INACTIVITY_MINUTES"] == 7
