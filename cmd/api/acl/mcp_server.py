"""Provide generic FastMCP helpers shared by adapter servers."""

import contextvars
import functools
import inspect
from typing import Any, Callable

import anyio.to_thread


def expose_function(func: Callable[..., Any]) -> Callable[..., Any]:
    """Return a callable whose parameter names never start with an underscore.

    FastMCP rejects private parameter names. Functions without them are
    returned unchanged; otherwise a wrapper publishes the stripped names and
    forwards each call to the original parameters.
    """

    signature = inspect.signature(func)
    renamed = {
        name: name.lstrip("_") for name in signature.parameters if name.startswith("_")
    }
    if not renamed:
        return func

    original_by_public = {public: name for name, public in renamed.items()}
    public_signature = signature.replace(
        parameters=[
            parameter.replace(name=renamed.get(name, name))
            for name, parameter in signature.parameters.items()
        ]
    )

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        """Forward public argument names to the wrapped function."""

        return func(
            *args,
            **{
                original_by_public.get(key, key): value for key, value in kwargs.items()
            },
        )

    wrapper.__signature__ = public_signature
    return wrapper


def run_in_worker_thread(func: Callable[..., Any]) -> Callable[..., Any]:
    """Return an async callable that runs a sync tool on a worker thread.

    FastMCP calls sync functions inline on the event loop, so a slow tool would
    stall every other request. The wrapper keeps the published signature.
    """

    exposed = expose_function(func)

    @functools.wraps(exposed)
    async def call(**kwargs: Any) -> Any:
        """Run the wrapped tool off the event loop."""

        ctx = contextvars.copy_context()
        return await anyio.to_thread.run_sync(
            ctx.run, functools.partial(exposed, **kwargs)
        )

    call.__signature__ = inspect.signature(exposed)
    return call
