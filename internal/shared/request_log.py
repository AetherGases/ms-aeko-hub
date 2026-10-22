"""Collect operations into one ASGI request log and persist request metrics.

Each request emits one block containing its path, status, duration, and operations.
Query strings are excluded. AEKO_LOG_STREAM enables immediate operation output.
Context variables isolate concurrent requests; each block is written once.
"""

from __future__ import annotations

import contextvars
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Callable

from internal.shared.constants import (
    BLUE,
    CRASHED_STATUS,
    FAILING_STATUS,
    INDENT,
    RED,
    TRUE_VALUES,
    UVICORN_ACCESS_LOGGER,
)
from internal.shared.event_tracking import (
    Event,
    answer_with_id_request,
    bind_id_request,
    endpoint_of,
    new_id_request,
    origin_of,
    record_event,
    unbind_id_request,
)
from internal.shared.logger import (
    Module,
    elapsed_since,
    format_entry,
    paint,
    write,
)


@dataclass(frozen=True)
class Record:
    """One finished operation, kept until the request it belongs to ends."""

    module: str
    subject: str
    elapsed: str
    error: str = ""

    @property
    def failed(self) -> bool:
        """Return whether the operation recorded an error."""
        return self.error != ""

    def description(self) -> str:
        """Format the operation subject, elapsed time, and outcome."""

        if self.failed:
            return f"{self.subject} failed after {self.elapsed}: {self.error}"
        return f"{self.subject} succeeded in {self.elapsed}"


_records: contextvars.ContextVar[list[Record] | None] = contextvars.ContextVar(
    "aeko_request_records", default=None
)


def streaming() -> bool:
    """Return whether the environment enables immediate operation log output."""

    return os.environ.get("AEKO_LOG_STREAM", "").strip().lower() in TRUE_VALUES


def collect(record: Record) -> bool:
    """Append an operation to the current request, returning False outside a request."""

    records = _records.get()
    if records is None:
        return False

    records.append(record)
    return True


def _widths(records: list[Record]) -> tuple[int, int]:
    """Return the maximum rendered module and subject widths for alignment."""

    module = max(len(f"[{record.module}]") for record in records)
    subject = max(len(record.subject) for record in records)
    return module, subject


def render(records: list[Record]) -> list[str]:
    """Format operations as aligned, indented lines with outcome colors."""

    if not records:
        return []

    module_width, subject_width = _widths(records)
    elapsed_width = max(len(record.elapsed) for record in records)

    lines = []
    for record in records:
        tag = f"[{record.module}]".ljust(module_width)
        subject = record.subject.ljust(subject_width)
        outcome = "failed after" if record.failed else "succeeded in"
        line = f"{INDENT}{tag} {subject} {outcome} {record.elapsed:>{elapsed_width}}"
        if record.failed:
            line = f"{line}: {record.error}"
        lines.append(paint(line, RED if record.failed else BLUE))

    return lines


def _counted(records: list[Record] | None) -> str:
    """Format the operation count, omitting it in streaming mode."""

    if records is None:
        return ""
    if len(records) == 1:
        return " (1 operation)"
    return f" ({len(records)} operations)"


def header(
    method: str,
    path: str,
    status: int | None,
    elapsed: str,
    records: list[Record] | None,
    error: str = "",
) -> str:
    """Format the request method, path, status, duration, operation count, and error."""

    shown = status if status is not None else "-"
    line = f"{method} {path} -> {shown} in {elapsed}{_counted(records)}"
    if error:
        line = f"{line} | raised {error}"
    return line


def emit(
    method: str,
    path: str,
    status: int | None,
    elapsed: str,
    records: list[Record] | None,
    error: str = "",
) -> None:
    """Write a colored request header and its operations as a single log block."""

    failed = error != "" or status is None or status >= FAILING_STATUS
    line = format_entry(
        Module.REQUEST, header(method, path, status, elapsed, records, error)
    )
    block = [paint(line, RED if failed else BLUE), *render(records or [])]
    write("\n".join(block))


def silence_uvicorn_access_log() -> None:
    """Disable Uvicorn access logging after server logging has been configured."""

    logging.getLogger(UVICORN_ACCESS_LOGGER).disabled = True


class RequestLogMiddleware:
    """Collect operation logs and metrics in the same ASGI task as the request."""

    def __init__(self, app: Callable) -> None:
        """Wrap the inner ASGI application with request logging."""
        self.app = app

    def _close(
        self,
        scope: dict,
        method: str,
        path: str,
        status: int | None,
        started: float,
        records: list[Record] | None,
        id_request: str,
        error: str = "",
    ) -> None:
        """Persist the request metric before emitting its log block using the same elapsed time."""

        elapsed = elapsed_since(started)
        record_event(
            Event(
                id_request=id_request,
                latency=elapsed,
                response_status=status if status is not None else CRASHED_STATUS,
                endpoint=endpoint_of(scope),
                origin=origin_of(path),
            )
        )
        emit(method, path, status, elapsed, records, error)

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        """Log HTTP requests and persist hub metrics for each response."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        records: list[Record] | None = None if streaming() else []
        token = _records.set(records)
        started = time.perf_counter()
        status: dict[str, Any] = {"code": None}

        id_request = new_id_request()

        id_token = bind_id_request(id_request)

        async def send_wrapper(message: dict) -> None:
            """Capture the response status, attach the request identifier, and forward the message."""
            if message["type"] == "http.response.start":
                status["code"] = message["status"]

                answer_with_id_request(message, id_request)
            await send(message)

        method = scope.get("method", "?")

        path = scope.get("path", "?")

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception as exc:
            self._close(
                scope,
                method,
                path,
                status["code"],
                started,
                records,
                id_request,
                f"{type(exc).__name__}: {exc}",
            )
            raise
        else:
            self._close(
                scope, method, path, status["code"], started, records, id_request
            )
        finally:
            unbind_id_request(id_token)
            _records.reset(token)
