"""AgentTool adapter for remote MCP tools."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Callable

from ...core.tools.base import AgentTool
from ...core.types import AgentToolResult, ToolCall
from .config import mcp_registered_tool_name


@dataclass(frozen=True)
class MCPRemoteTool:
    """Normalized metadata for a tool discovered from an MCP server."""

    name: str
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)


class MCPTool(AgentTool):
    """Wrap a remote MCP tool as an ark-agentic ``AgentTool``."""

    name = "mcp_tool"
    description = "MCP tool"
    parameters = []
    visibility = "auto"

    def __init__(
        self,
        *,
        server_id: str,
        remote_tool: MCPRemoteTool,
        session_provider: Callable[[str], Any],
        timeout: float = 30.0,
    ) -> None:
        self.server_id = server_id
        self.remote_name = remote_tool.name
        self.name = mcp_registered_tool_name(server_id, remote_tool.name)
        self.description = (
            remote_tool.description or f"MCP tool {remote_tool.name}"
        )
        self.input_schema = _ensure_object_schema(remote_tool.input_schema)
        self.timeout = timeout
        self._session_provider = session_provider
        self.group = f"mcp:{server_id}"
        self.thinking_hint = f"正在调用 MCP 工具 {remote_tool.name}…"

    def get_json_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_schema,
            },
        }

    async def execute(
        self,
        tool_call: ToolCall,
        context: dict[str, Any] | None = None,
    ) -> AgentToolResult:
        del context
        args = tool_call.arguments or {}
        session = self._session_provider(self.server_id)
        try:
            result = await asyncio.wait_for(
                session.call_tool(self.remote_name, args),
                timeout=self.timeout,
            )
        except asyncio.TimeoutError:
            return AgentToolResult.error_result(
                tool_call.id,
                (
                    f"MCP tool '{self.remote_name}' "
                    f"timed out after {self.timeout}s"
                ),
                metadata=self._metadata(),
            )
        except Exception as exc:
            return AgentToolResult.error_result(
                tool_call.id,
                f"MCP tool '{self.remote_name}' failed: {exc}",
                metadata=self._metadata(),
            )

        content = _extract_result_content(result)
        is_error = bool(
            getattr(result, "isError", False)
            or getattr(result, "is_error", False)
        )
        if is_error:
            return AgentToolResult.error_result(
                tool_call.id,
                _stringify_for_error(content),
                metadata=self._metadata(),
            )

        if isinstance(content, str):
            return AgentToolResult.text_result(
                tool_call.id,
                content,
                metadata=self._metadata(),
            )
        return AgentToolResult.json_result(
            tool_call.id,
            content,
            metadata=self._metadata(),
        )

    def _metadata(self) -> dict[str, Any]:
        return {
            "source": "mcp",
            "mcp_server_id": self.server_id,
            "mcp_tool_name": self.remote_name,
        }


def normalize_mcp_tool(raw: Any) -> MCPRemoteTool:
    """Normalize SDK tool objects or dicts into ``MCPRemoteTool``."""
    if isinstance(raw, dict):
        name = str(raw.get("name") or "")
        description = str(raw.get("description") or "")
        input_schema = raw.get("inputSchema") or raw.get("input_schema") or {}
        return MCPRemoteTool(
            name=name,
            description=description,
            input_schema=_as_dict(input_schema),
        )

    input_schema = (
        getattr(raw, "inputSchema", None)
        or getattr(raw, "input_schema", None)
        or {}
    )
    return MCPRemoteTool(
        name=str(getattr(raw, "name", "") or ""),
        description=str(getattr(raw, "description", "") or ""),
        input_schema=_as_dict(input_schema),
    )


def _ensure_object_schema(schema: dict[str, Any]) -> dict[str, Any]:
    if not schema:
        return {"type": "object", "properties": {}, "required": []}
    if schema.get("type") != "object":
        schema = {"type": "object", "properties": {}, **schema}
    schema.setdefault("properties", {})
    schema.setdefault("required", [])
    return schema


def _extract_result_content(result: Any) -> Any:
    structured = getattr(result, "structuredContent", None)
    if structured is None:
        structured = getattr(result, "structured_content", None)
    if structured is not None:
        return _to_plain(structured)

    content_items = getattr(result, "content", None)
    if not content_items:
        return {}

    normalized = [_content_item_to_plain(item) for item in content_items]
    text_items = [
        item["text"]
        for item in normalized
        if isinstance(item, dict) and item.get("type") == "text"
    ]
    if text_items and len(text_items) == len(normalized):
        return "\n".join(text_items)
    return normalized


def _content_item_to_plain(item: Any) -> Any:
    if isinstance(item, dict):
        return _to_plain(item)

    text = getattr(item, "text", None)
    if text is not None:
        return {"type": "text", "text": str(text)}

    data = getattr(item, "data", None)
    mime_type = (
        getattr(item, "mimeType", None)
        or getattr(item, "mime_type", None)
    )
    if data is not None:
        return {"type": "image", "data": data, "mime_type": mime_type}

    resource = getattr(item, "resource", None)
    if resource is not None:
        return {"type": "resource", "resource": _to_plain(resource)}

    return _to_plain(item)


def _as_dict(value: Any) -> dict[str, Any]:
    plain = _to_plain(value)
    return plain if isinstance(plain, dict) else {}


def _to_plain(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(by_alias=True)
    if hasattr(value, "dict"):
        return value.dict()
    if isinstance(value, dict):
        return {str(k): _to_plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_plain(v) for v in value]
    if isinstance(value, tuple):
        return [_to_plain(v) for v in value]
    return value


def _stringify_for_error(content: Any) -> str:
    if isinstance(content, str):
        return content
    return str(content)
