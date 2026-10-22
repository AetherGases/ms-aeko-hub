"""Verify logger behavior and error handling."""

import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

import internal.shared as shared
from internal.shared.logger import (
    APP_NAME,
    BLUE,
    RED,
    RESET,
    Module,
    color_enabled,
    format_entry,
    log_failure,
    log_success,
)
from internal.shared.operation import logged, operation

MOMENT = datetime(2026, 9, 3, 10, 15, 30, tzinfo=timezone.utc)


LINE = re.compile(
    r"^\[aeko-hub\] \[(?P<module>\w+)\] "
    r"\[(?P<stamp>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)\] "
    r"(?P<description>.*)$"
)

DURATION = re.compile(r"\d+\.\d+ms")


@pytest.fixture(autouse=True)
def no_color_override(monkeypatch):
    """Clear the color override for terminal-detection tests."""
    monkeypatch.delenv("AEKO_LOG_COLOR", raising=False)


class Stream:
    """A stdout double that answers `isatty` however the test needs it to."""

    def __init__(self, tty=False):
        self.tty = tty
        self.written = []

    def isatty(self):
        """Report the simulated terminal capability."""
        return self.tty

    def write(self, text):
        """Append output to the simulated stream."""
        self.written.append(text)

    def flush(self):
        """Implement the simulated stream flush behavior."""
        pass

    @property
    def text(self):
        """Return the text captured by the simulated stream."""
        return "".join(self.written)


def only_line(captured):
    """Return the single captured log line."""
    lines = [line for line in captured.out.splitlines() if line]
    assert len(lines) == 1, captured.out
    return lines[0]


def test_format_entry_writes_the_agreed_shape():
    """Verify that format entry writes the agreed shape."""
    entry = format_entry(Module.DATABASE, "session.get_session ok", moment=MOMENT)
    assert (
        entry
        == f"[{APP_NAME}] [database] [2026-09-03T10:15:30Z] session.get_session ok"
    )


def test_format_entry_names_the_application_in_every_line():
    """Verify that format entry names the application in every line."""
    assert format_entry(Module.TOOL, "calculator", moment=MOMENT).startswith(
        "[aeko-hub] "
    )


@pytest.mark.parametrize(
    "module, expected",
    [
        (Module.DATABASE, "database"),
        (Module.MCP, "mcp"),
        (Module.TOOL, "tool"),
        (Module.INTEGRATION, "integration"),
    ],
)
def test_format_entry_writes_the_module_value_not_its_member_name(module, expected):
    """Verify that format entry writes the module value not its member name."""
    assert LINE.match(format_entry(module, "x", moment=MOMENT))["module"] == expected


def test_format_entry_accepts_a_plain_string_module():
    """Verify that format entry accepts a plain string module."""
    assert (
        LINE.match(format_entry("database", "x", moment=MOMENT))["module"] == "database"
    )


def test_format_entry_stamps_utc_rather_than_local_time():
    """Verify that format entry stamps utc rather than local time."""
    noon = datetime(2026, 9, 3, 15, 0, 0, tzinfo=timezone.utc)
    assert "T15:00:00Z" in format_entry(Module.MCP, "x", moment=noon)


def test_format_entry_stamps_now_when_no_moment_is_given():
    """Verify that format entry stamps now when no moment is given."""
    entry = format_entry(Module.MCP, "x")
    stamp = LINE.match(entry)["stamp"]
    assert stamp == datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_format_entry_keeps_the_description_verbatim():
    """Verify that format entry keeps the description verbatim."""
    description = (
        "chroma.query_gases_info failed after 3.2ms: LookupError: no such tool"
    )
    assert format_entry(Module.MCP, description, moment=MOMENT).endswith(description)


def test_color_is_written_to_a_terminal():
    """Verify that color is written to a terminal."""
    assert color_enabled(Stream(tty=True)) is True


def test_color_is_withheld_from_a_redirected_stream():
    """Verify that color is withheld from a redirected stream."""
    assert color_enabled(Stream(tty=False)) is False


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
def test_color_override_turns_it_on_for_a_file(monkeypatch, value):
    """Verify that color override turns it on for a file."""
    monkeypatch.setenv("AEKO_LOG_COLOR", value)
    assert color_enabled(Stream(tty=False)) is True


@pytest.mark.parametrize("value", ["0", "false", "FALSE", "no", "off"])
def test_color_override_turns_it_off_for_a_terminal(monkeypatch, value):
    """Verify that color override turns it off for a terminal."""
    monkeypatch.setenv("AEKO_LOG_COLOR", value)
    assert color_enabled(Stream(tty=True)) is False


def test_an_unreadable_override_falls_back_to_asking_the_stream(monkeypatch):
    """Verify that an unreadable override falls back to asking the stream."""
    monkeypatch.setenv("AEKO_LOG_COLOR", "maybe")
    assert color_enabled(Stream(tty=True)) is True
    assert color_enabled(Stream(tty=False)) is False


def test_a_stream_without_isatty_is_not_a_terminal():
    """Verify that a stream without isatty is not a terminal."""

    class Bare:
        def write(self, text):
            """Append output to the simulated stream."""
            pass

    assert color_enabled(Bare()) is False


def test_a_stream_that_refuses_the_question_is_not_a_terminal():
    """Verify that a stream that refuses the question is not a terminal."""

    class Hostile:
        def isatty(self):
            """Report the simulated terminal capability."""
            raise ValueError("closed")

    assert color_enabled(Hostile()) is False


def test_color_asks_the_current_stdout_when_no_stream_is_given(monkeypatch):
    """Verify that color asks the current stdout when no stream is given."""
    monkeypatch.setattr(sys, "stdout", Stream(tty=True))
    assert color_enabled() is True


def test_success_writes_one_line_in_the_agreed_shape(capsys):
    """Verify that success writes one line in the agreed shape."""
    log_success(Module.DATABASE, "user.get_user succeeded in 1.0ms")
    line = LINE.match(only_line(capsys.readouterr()))
    assert line["module"] == "database"
    assert line["description"] == "user.get_user succeeded in 1.0ms"


def test_failure_writes_one_line_in_the_agreed_shape(capsys):
    """Verify that failure writes one line in the agreed shape."""
    log_failure(
        Module.MCP, "chroma.start failed after 2.0ms: MCPSessionError: no server"
    )
    line = LINE.match(only_line(capsys.readouterr()))
    assert line["module"] == "mcp"
    assert line["description"].startswith("chroma.start failed after ")


def test_nothing_is_written_to_stderr(capsys):
    """Verify that nothing is written to stderr."""
    log_failure(Module.MCP, "chroma.start failed")
    assert capsys.readouterr().err == ""


def test_success_is_blue_on_a_terminal(monkeypatch):
    """Verify that success is blue on a terminal."""
    stream = Stream(tty=True)
    monkeypatch.setattr(sys, "stdout", stream)
    log_success(Module.DATABASE, "ok")
    assert stream.text.startswith(BLUE)
    assert stream.text.rstrip("\n").endswith(RESET)


def test_failure_is_red_on_a_terminal(monkeypatch):
    """Verify that failure is red on a terminal."""
    stream = Stream(tty=True)
    monkeypatch.setattr(sys, "stdout", stream)
    log_failure(Module.DATABASE, "boom")
    assert stream.text.startswith(RED)
    assert stream.text.rstrip("\n").endswith(RESET)


def test_the_two_outcomes_do_not_share_a_color():
    """Verify that the two outcomes do not share a color."""
    assert BLUE != RED


def test_no_escape_codes_reach_a_redirected_stream(capsys):
    """Verify that no escape codes reach a redirected stream."""
    log_success(Module.TOOL, "calculator succeeded in 0.1ms")
    log_failure(Module.TOOL, "calculator failed after 0.1ms")
    assert "\033" not in capsys.readouterr().out


def test_the_stream_is_resolved_at_call_time(monkeypatch):
    """Verify that the stream is resolved at call time."""
    first, second = Stream(), Stream()
    monkeypatch.setattr(sys, "stdout", first)
    log_success(Module.MCP, "one")
    monkeypatch.setattr(sys, "stdout", second)
    log_success(Module.MCP, "two")
    assert "one" in first.text and "two" not in first.text
    assert "two" in second.text


def test_operation_logs_once_when_the_block_ends(capsys):
    """Verify that operation logs once when the block ends."""
    with operation(Module.DATABASE, "session.get_session"):
        pass
    line = LINE.match(only_line(capsys.readouterr()))
    assert line["module"] == "database"
    assert line["description"].startswith("session.get_session succeeded in ")


def test_operation_reports_how_long_the_work_took(capsys):
    """Verify that operation reports how long the work took."""
    with operation(Module.MCP, "chroma.query_gases_info"):
        pass
    assert DURATION.search(capsys.readouterr().out)


def test_operation_says_nothing_before_the_block_ends(capsys):
    """Verify that operation says nothing before the block ends."""
    with operation(Module.MCP, "chroma.start"):
        assert capsys.readouterr().out == ""


def test_operation_names_the_error_when_the_block_raises(capsys):
    """Verify that operation names the error when the block raises."""
    with pytest.raises(RuntimeError):
        with operation(Module.DATABASE, "session.save_message"):
            raise RuntimeError("connection refused")

    description = LINE.match(only_line(capsys.readouterr()))["description"]
    assert description.startswith("session.save_message failed after ")
    assert description.endswith(": RuntimeError: connection refused")


def test_operation_re_raises_the_original_exception():
    """Verify that operation re raises the original exception."""
    original = ValueError("User with id_external_user 7 not found.")
    with pytest.raises(ValueError) as raised:
        with operation(Module.DATABASE, "user.get_user"):
            raise original
    assert raised.value is original


def test_operation_is_red_on_failure_and_blue_on_success(monkeypatch):
    """Verify that operation is red on failure and blue on success."""
    stream = Stream(tty=True)
    monkeypatch.setattr(sys, "stdout", stream)

    with operation(Module.TOOL, "calculator"):
        pass
    with pytest.raises(ValueError):
        with operation(Module.TOOL, "calculator"):
            raise ValueError("nope")

    written = stream.text.splitlines()
    assert written[0].startswith(BLUE)
    assert written[1].startswith(RED)


def test_operation_appends_the_detail_to_the_name(capsys):
    """Verify that operation appends the detail to the name."""
    with operation(Module.MCP, "tavily.start", "over stdio via npx"):
        pass
    assert "tavily.start over stdio via npx succeeded in " in capsys.readouterr().out


def test_operation_without_detail_leaves_no_double_space(capsys):
    """Verify that operation without detail leaves no double space."""
    with operation(Module.MCP, "tavily.start"):
        pass
    assert "tavily.start  " not in capsys.readouterr().out


def test_logged_returns_what_the_function_returned(capsys):
    """Verify that logged returns what the function returned."""

    @logged(Module.TOOL, "calculator")
    def calculate(expression):
        """Exercise calculator operation logging."""
        return "4"

    assert calculate("2 + 2") == "4"
    assert "calculator succeeded in " in capsys.readouterr().out


def test_logged_falls_back_to_the_function_name(capsys):
    """Verify that logged falls back to the function name."""

    @logged(Module.TOOL)
    def calculate():
        """Exercise calculator operation logging."""
        return None

    calculate()
    assert "calculate succeeded in " in capsys.readouterr().out


def test_logged_keeps_the_function_recognisable():
    """Verify that logged keeps the function recognisable."""

    @logged(Module.DATABASE, "user.get_user")
    def get_user(self, id_external_user):
        """Docstring that must survive."""
        return None

    assert get_user.__name__ == "get_user"
    assert get_user.__doc__ == "Docstring that must survive."


def test_logged_passes_every_argument_through():
    """Verify that logged passes every argument through."""
    seen = {}

    @logged(Module.DATABASE, "session.save_message")
    def save(id_session, message=None):
        """Exercise persistence operation logging."""
        seen.update(id_session=id_session, message=message)
        return "saved"

    assert save("s-1", message="m") == "saved"
    assert seen == {"id_session": "s-1", "message": "m"}


def test_logged_reports_and_re_raises(capsys):
    """Verify that logged reports and re raises."""

    @logged(Module.INTEGRATION, "climatiq.search")
    def search():
        """Exercise search operation logging."""
        raise RuntimeError("Climatiq returned 502")

    with pytest.raises(RuntimeError):
        search()

    description = LINE.match(only_line(capsys.readouterr()))["description"]
    assert description.startswith("climatiq.search failed after ")
    assert description.endswith(": RuntimeError: Climatiq returned 502")


def test_shared_never_imports_the_sdk():
    """Verify that shared never imports the sdk."""
    package = Path(shared.__file__).parent
    modules = sorted(package.glob("*.py"))
    assert modules, "the shared package has no modules to check"

    for module in modules:
        source = module.read_text(encoding="utf-8")
        assert "import aeko" not in source, module.name
        assert "from aeko" not in source, module.name
