"""Record operation duration and outcome without changing return values or errors.

Operations join the current request log when available and are emitted
immediately outside a request.
"""

from __future__ import annotations

import functools
import time
from contextlib import contextmanager
from typing import Any, Callable, Iterator

from internal.shared.logger import Module, elapsed_since, log_failure, log_success
from internal.shared.request_log import Record, collect


def _subject(name: str, detail: str) -> str:
    """Return a printable subject label for an operation."""
    return f"{name} {detail}".strip()


def _finish(module: Module | str, subject: str, started: float, error: str) -> None:
    """Add a completed operation to the request log or emit it immediately."""

    name = module.value if isinstance(module, Module) else str(module)
    record = Record(
        module=name,
        subject=subject,
        elapsed=elapsed_since(started),
        error=error,
    )

    if collect(record):
        return

    log = log_failure if record.failed else log_success
    log(module, record.description())


@contextmanager
def operation(
    module: Module | str,
    name: str,
    detail: str = "",
) -> Iterator[None]:
    """Record the duration and outcome of a block, propagating any exception."""

    subject = _subject(name, detail)
    started = time.perf_counter()
    try:
        yield
    except Exception as exc:
        _finish(module, subject, started, f"{type(exc).__name__}: {exc}")
        raise

    _finish(module, subject, started, "")


def logged(
    module: Module | str,
    name: str | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorate a function to record its duration and outcome under an operation name."""

    def decorate(func: Callable[..., Any]) -> Callable[..., Any]:
        """Wrap the function with operation logging while preserving its metadata."""
        subject = name or func.__name__

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            """Invoke the wrapped function within a timed operation."""
            with operation(module, subject):
                return func(*args, **kwargs)

        return wrapper

    return decorate
