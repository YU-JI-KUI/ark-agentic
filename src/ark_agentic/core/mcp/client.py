"""MCP client session lifecycle wrappers."""

from __future__ import annotations

import asyncio
import inspect
from contextlib import AsyncExitStack
from typing import Any

import httpx

from .config import MCPServerConfig
from .tool import MCPRemoteTool, normalize_mcp_tool


class MCPDependencyError(RuntimeError):
    """Raised when MCP config exists but the optional SDK is unavailable."""


class MCPServerRuntime:
    """One connected MCP server session plus discovered tool metadata."""

    def __init__(self, config: MCPServerConfig) -> None:
        self.config = config
        self.status = "pending"
        self.error: str | None = None
        self.tools: list[MCPRemoteTool] = []
        self._stack: AsyncExitStack | None = None
        self._session: Any = None

    async def connect(self) -> None:
        stack = AsyncExitStack()
        try:
            read, write = await self._open_transport(stack)
            try:
                from mcp import ClientSession
            except ImportError as exc:
                raise MCPDependencyError(
                    "MCP support requires optional dependency: "
                    "ark-agentic[mcp]"
                ) from exc

            session = await stack.enter_async_context(
                ClientSession(read, write)
            )
            await asyncio.wait_for(
                session.initialize(),
                timeout=self.config.timeout,
            )
            result = await asyncio.wait_for(
                session.list_tools(),
                timeout=self.config.timeout,
            )
            self.tools = [
                t for t in (normalize_mcp_tool(raw) for raw in result.tools)
                if t.name
            ]
            self._session = session
            self._stack = stack
            self.status = "connected"
            self.error = None
        except Exception as exc:
            await stack.aclose()
            self.status = "error"
            self.error = str(exc)
            raise

    async def close(self) -> None:
        if self._stack is not None:
            await self._stack.aclose()
        self._stack = None
        self._session = None
        if self.status != "error":
            self.status = "closed"

    def get_session(self) -> Any:
        if self._session is None:
            raise RuntimeError(
                f"MCP server '{self.config.id}' is not connected"
            )
        return self._session

    def allowed_tools(self) -> list[MCPRemoteTool]:
        return [
            tool for tool in self.tools
            if self.config.tools.is_allowed(tool.name)
        ]

    async def _open_transport(self, stack: AsyncExitStack) -> tuple[Any, Any]:
        if self.config.transport == "stdio":
            try:
                from mcp import StdioServerParameters
                from mcp.client.stdio import stdio_client
            except ImportError as exc:
                raise MCPDependencyError(
                    "MCP stdio support requires optional dependency: "
                    "ark-agentic[mcp]"
                ) from exc
            params = StdioServerParameters(
                command=self.config.command or "",
                args=self.config.args,
                env=self.config.env or None,
            )
            read, write = await stack.enter_async_context(stdio_client(params))
            return read, write

        try:
            from mcp.client import streamable_http as http_transport
        except ImportError as exc:
            raise MCPDependencyError(
                "MCP HTTP support requires optional dependency: "
                "ark-agentic[mcp]"
            ) from exc

        streamable_http_client = getattr(
            http_transport,
            "streamable_http_client",
            None,
        )
        if streamable_http_client is None:
            streamable_http_client = getattr(
                http_transport,
                "streamablehttp_client",
                None,
            )
        if streamable_http_client is None:
            raise MCPDependencyError(
                "MCP HTTP transport is unavailable in the installed MCP SDK"
            )

        kwargs = await self._streamable_http_client_kwargs(
            streamable_http_client,
            stack,
        )
        opened = await stack.enter_async_context(
            streamable_http_client(self.config.url or "", **kwargs)
        )
        read = opened[0]
        write = opened[1]
        return read, write

    async def _streamable_http_client_kwargs(
        self,
        streamable_http_client: Any,
        stack: AsyncExitStack,
    ) -> dict[str, Any]:
        headers = self.config.headers or None

        try:
            parameters = inspect.signature(
                streamable_http_client,
            ).parameters
        except (TypeError, ValueError):
            parameters = {}

        if "http_client" in parameters:
            timeout = httpx.Timeout(
                self.config.timeout,
                read=max(300.0, self.config.timeout),
            )
            client = await stack.enter_async_context(
                httpx.AsyncClient(
                    follow_redirects=True,
                    headers=headers,
                    timeout=timeout,
                    trust_env=False,
                )
            )
            return {"http_client": client}
        if "headers" in parameters and headers:
            return {"headers": headers}
        return {}
