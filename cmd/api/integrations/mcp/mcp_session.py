"""Maintain one MCP session per server on a dedicated event-loop thread.

Session entry and exit run in the same task. Tool calls have bounded waits and
retry once after connection failures; clients are constructed lazily.
"""

import asyncio
import concurrent.futures
import threading
from typing import Any, Callable

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools

from internal.shared import Module, log_success, operation


from cmd.api.integrations.mcp.constants import (
    DEFAULT_STARTUP_TIMEOUT,
    DEFAULT_CALL_TIMEOUT,
    DEFAULT_CLOSE_TIMEOUT,
)


class MCPSessionError(RuntimeError):
    """Raised when a tool call cannot be completed over the MCP session."""


class PersistentMCPSession:
    """Share a lazily constructed MCP client and persistent session across callers."""

    def __init__(
        self,
        server_name: str,
        build_client: Callable[[], MultiServerMCPClient],
        call_timeout: float = DEFAULT_CALL_TIMEOUT,
        startup_timeout: float = DEFAULT_STARTUP_TIMEOUT,
        close_timeout: float = DEFAULT_CLOSE_TIMEOUT,
    ) -> None:
        """Configure the long-lived MCP child session."""
        self.name = server_name
        self._server_name = server_name
        self._build_client = build_client
        self._call_timeout = call_timeout
        self._startup_timeout = startup_timeout
        self._close_timeout = close_timeout

        self._lock = threading.RLock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._tools: dict[str, BaseTool] | None = None
        self._closing: asyncio.Event | None = None
        self._keeper: concurrent.futures.Future | None = None

    def start(self) -> None:
        """Open the MCP session if it is not already available."""

        self._ensure_started()

    def close(self) -> None:
        """Close the MCP session and stop its event loop within the shutdown timeout."""

        with self._lock:
            loop, keeper, closing = self._loop, self._keeper, self._closing
            self._loop = self._thread = self._tools = self._closing = self._keeper = (
                None
            )

        if loop is None:
            return

        if closing is not None:
            loop.call_soon_threadsafe(closing.set)

        if keeper is not None:
            try:
                keeper.result(timeout=self._close_timeout)
            except Exception:
                pass

        loop.call_soon_threadsafe(loop.stop)

        log_success(Module.MCP, f"{self._server_name}.close ended the session")

    def call_tool(self, tool_name: str, **kwargs: Any) -> Any:
        """Run an MCP tool synchronously, retrying once after a connection failure."""

        with operation(Module.MCP, f"{self._server_name}.{tool_name}"):
            last_error: Exception | None = None
            for attempt in (1, 2):
                tool = self._resolve_tool(tool_name)
                try:
                    return self._run(tool.ainvoke(kwargs))
                except MCPSessionError:
                    raise
                except Exception as exc:
                    last_error = exc
                    self.close()

            raise MCPSessionError(
                f"'{tool_name}' failed on the {self._server_name} MCP server: {last_error}"
            ) from last_error

    def _run(self, coroutine: Any) -> Any:
        """Run a coroutine on the session event loop and return its result."""
        loop = self._loop
        if loop is None:
            raise ConnectionError("the MCP session was closed")

        future = asyncio.run_coroutine_threadsafe(coroutine, loop)
        try:
            return future.result(timeout=self._call_timeout)
        except concurrent.futures.TimeoutError:
            future.cancel()
            self.close()
            raise MCPSessionError(
                f"the {self._server_name} MCP server did not answer within "
                f"{self._call_timeout:.0f}s. The session was dropped; the next "
                f"call starts a new server."
            ) from None

    def _resolve_tool(self, tool_name: str) -> BaseTool:
        """Return a loaded tool by name, or raise if it is missing."""
        tools = self._ensure_started()
        if tool_name in tools:
            return tools[tool_name]

        known = ", ".join(sorted(tools))
        raise LookupError(
            f"'{tool_name}' is not exposed by the {self._server_name} MCP server. "
            f"Available tools: {known}."
        )

    def _ensure_started(self) -> dict[str, BaseTool]:
        """Start the child session thread if it is not already running."""
        with self._lock:
            if self._tools is not None:
                return self._tools

            with operation(Module.MCP, f"{self._server_name}.start"):
                client = self._build_client()
                loop = asyncio.new_event_loop()
                thread = threading.Thread(
                    target=self._run_loop,
                    args=(loop,),
                    name=f"mcp-{self._server_name}",
                    daemon=True,
                )
                thread.start()

                ready: concurrent.futures.Future = concurrent.futures.Future()
                keeper = asyncio.run_coroutine_threadsafe(
                    self._keep_open(client, ready), loop
                )

                try:
                    tools = ready.result(timeout=self._startup_timeout)
                except Exception as exc:
                    keeper.cancel()
                    loop.call_soon_threadsafe(loop.stop)
                    raise MCPSessionError(
                        f"could not open a session with the {self._server_name} "
                        f"MCP server: {exc}"
                    ) from exc

                self._loop, self._thread, self._tools, self._keeper = (
                    loop,
                    thread,
                    tools,
                    keeper,
                )
                return tools

    @staticmethod
    def _run_loop(loop: asyncio.AbstractEventLoop) -> None:
        """Run the MCP client session until close is requested."""
        asyncio.set_event_loop(loop)
        try:
            loop.run_forever()
        finally:
            loop.close()

    async def _keep_open(
        self,
        client: MultiServerMCPClient,
        ready: concurrent.futures.Future,
    ) -> None:
        """Enter and exit the MCP session in one task, keeping it open until shutdown."""

        closing = asyncio.Event()
        self._closing = closing
        try:
            async with client.session(self._server_name) as session:
                tools = await load_mcp_tools(session)
                ready.set_result({tool.name: tool for tool in tools})
                await closing.wait()
        except BaseException as exc:
            if not ready.done():
                ready.set_exception(exc)
