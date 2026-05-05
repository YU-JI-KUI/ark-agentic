"""JSONL session transcript format — types, codec, and validation error.

Defines the on-disk (and in-DB) representation of a session transcript:
entry dataclasses (SessionHeader, MessageEntry), serialization helpers
(serialize_message / deserialize_message etc.), and the validation error
raised when a raw JSONL write-back fails schema checks.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from ..types import (
    AgentMessage,
    AgentToolResult,
    MessageRole,
    ToolCall,
    ToolResultType,
    TurnContext,
)

logger = logging.getLogger(__name__)


class RawJsonlValidationError(Exception):
    """JSONL 校验失败，用于 PUT .../raw 写回。"""

    def __init__(self, message: str, line_number: int | None = None):
        self.line_number = line_number
        super().__init__(message)


# ── Constants ──────────────────────────────────────────────────────────────

SESSION_VERSION = 1


# ── Entry types ────────────────────────────────────────────────────────────


@dataclass
class SessionHeader:
    """JSONL 文件头"""

    type: Literal["session"] = "session"
    version: int = SESSION_VERSION
    id: str = ""
    timestamp: str = ""
    cwd: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "version": self.version,
            "id": self.id,
            "timestamp": self.timestamp,
            "cwd": self.cwd,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SessionHeader:
        return cls(
            type=data.get("type", "session"),
            version=data.get("version", SESSION_VERSION),
            id=data.get("id", ""),
            timestamp=data.get("timestamp", ""),
            cwd=data.get("cwd", ""),
        )


@dataclass
class MessageEntry:
    """JSONL 消息条目"""

    type: Literal["message"] = "message"
    message: dict[str, Any] = field(default_factory=dict)
    timestamp: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "message": self.message,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MessageEntry:
        return cls(
            type=data.get("type", "message"),
            message=data.get("message", {}),
            timestamp=data.get("timestamp", 0),
        )


# ── Codec ──────────────────────────────────────────────────────────────────


def serialize_tool_call(tc: ToolCall) -> dict[str, Any]:
    return {
        "id": tc.id,
        "type": "function",
        "function": {
            "name": tc.name,
            "arguments": json.dumps(tc.arguments, ensure_ascii=False),
        },
    }


def deserialize_tool_call(data: dict[str, Any]) -> ToolCall:
    func = data.get("function", {})
    args_str = func.get("arguments", "{}")
    try:
        arguments = json.loads(args_str) if isinstance(args_str, str) else args_str
    except json.JSONDecodeError:
        arguments = {}
    return ToolCall(
        id=data.get("id", ""),
        name=func.get("name", ""),
        arguments=arguments,
    )


def serialize_tool_result(tr: AgentToolResult) -> dict[str, Any]:
    content = tr.content
    if isinstance(content, (dict, list)):
        content = json.dumps(content, ensure_ascii=False)
    result: dict[str, Any] = {
        "tool_call_id": tr.tool_call_id,
        "result_type": tr.result_type.value if isinstance(tr.result_type, ToolResultType) else str(tr.result_type),
        "content": content,
        "is_error": tr.is_error,
    }
    if tr._llm_digest is not None:
        result["llm_digest"] = tr._llm_digest
    if tr.metadata:
        result["metadata"] = tr.metadata
    return result


def deserialize_tool_result(data: dict[str, Any]) -> AgentToolResult:
    content = data.get("content", "")
    is_error = data.get("is_error", False)
    stored_type = data.get("result_type")

    if stored_type is not None:
        try:
            result_type = ToolResultType(stored_type)
        except ValueError:
            result_type = ToolResultType.JSON
        if isinstance(content, str):
            try:
                content = json.loads(content)
            except json.JSONDecodeError:
                pass
    else:
        # Backward-compat: old JSONL without result_type field
        if isinstance(content, str):
            try:
                content = json.loads(content)
                result_type = ToolResultType.JSON
            except json.JSONDecodeError:
                result_type = ToolResultType.TEXT
        else:
            result_type = ToolResultType.JSON

    if is_error:
        result_type = ToolResultType.ERROR

    return AgentToolResult(
        tool_call_id=data.get("tool_call_id", ""),
        result_type=result_type,
        content=content,
        is_error=is_error,
        metadata=data.get("metadata") or None,
        llm_digest=data.get("llm_digest"),
    )


def serialize_message(msg: AgentMessage) -> dict[str, Any]:
    result: dict[str, Any] = {"role": msg.role.value}

    if msg.content is not None:
        result["content"] = [{"type": "text", "text": msg.content}]

    if msg.tool_calls:
        result["tool_calls"] = [serialize_tool_call(tc) for tc in msg.tool_calls]

    if msg.tool_results:
        result["tool_results"] = [serialize_tool_result(tr) for tr in msg.tool_results]

    if msg.thinking:
        result["thinking"] = msg.thinking

    if msg.metadata:
        result["metadata"] = msg.metadata

    if msg.finish_reason is not None:
        result["finish_reason"] = msg.finish_reason
    if msg.turn_context is not None:
        result["turn_context"] = {
            "active_skill_id": msg.turn_context.active_skill_id,
            "tools_mounted": msg.turn_context.tools_mounted,
        }

    return result


def parse_raw_jsonl(
    session_id: str, content: str,
) -> list[tuple[int, dict[str, Any]]]:
    """Validate a JSONL transcript blob and return its parsed message lines.

    Shared between the file and SQLite session backends — both accept the
    same `PUT .../raw` payload and apply identical schema rules:

    - line 1 is a ``session`` header with ``id == session_id``;
    - lines 2+ are ``message`` entries with a dict ``message`` field.

    Returns ``[(line_number, parsed_dict), ...]`` for every message line.
    Header is consumed but not returned. Raises
    ``RawJsonlValidationError`` on the first violation; nothing is
    persisted by this function.
    """
    lines = [line for line in content.splitlines() if line.strip()]
    if not lines:
        raise RawJsonlValidationError(
            "至少需要一行（session header）", line_number=1,
        )
    try:
        first = json.loads(lines[0])
    except json.JSONDecodeError as e:
        raise RawJsonlValidationError(
            f"首行非法 JSON: {e}", line_number=1,
        ) from e
    if first.get("type") != "session":
        raise RawJsonlValidationError(
            "首行 type 必须为 session", line_number=1,
        )
    header_id = (first.get("id") or "").strip()
    if header_id != session_id.strip():
        raise RawJsonlValidationError(
            f"首行 id 与 URL session_id 不一致: "
            f"{header_id!r} vs {session_id!r}",
            line_number=1,
        )

    messages: list[tuple[int, dict[str, Any]]] = []
    for i, line in enumerate(lines[1:], start=2):
        try:
            data = json.loads(line)
        except json.JSONDecodeError as e:
            raise RawJsonlValidationError(
                f"第 {i} 行非法 JSON: {e}", line_number=i,
            ) from e
        if data.get("type") != "message":
            raise RawJsonlValidationError(
                f"第 {i} 行 type 必须为 message", line_number=i,
            )
        if "message" not in data or not isinstance(data["message"], dict):
            raise RawJsonlValidationError(
                f"第 {i} 行必须含 message 对象", line_number=i,
            )
        messages.append((i, data))
    return messages


def deserialize_message(data: dict[str, Any]) -> AgentMessage:
    role_str = data.get("role", "user")
    role = MessageRole(role_str)

    content = None
    content_data = data.get("content")
    if isinstance(content_data, str):
        content = content_data
    elif isinstance(content_data, list):
        for item in content_data:
            if isinstance(item, dict) and item.get("type") == "text":
                content = item.get("text", "")
                break

    tool_calls = None
    tc_data = data.get("tool_calls")
    if tc_data and isinstance(tc_data, list):
        tool_calls = [deserialize_tool_call(tc) for tc in tc_data]

    tool_results = None
    tr_data = data.get("tool_results")
    if tr_data and isinstance(tr_data, list):
        tool_results = [deserialize_tool_result(tr) for tr in tr_data]

    ts = data.get("timestamp")
    timestamp = datetime.fromtimestamp(ts / 1000) if ts else datetime.now()

    turn_ctx = data.get("turn_context")
    return AgentMessage(
        role=role,
        content=content,
        tool_calls=tool_calls,
        tool_results=tool_results,
        thinking=data.get("thinking"),
        timestamp=timestamp,
        metadata=data.get("metadata", {}),
        finish_reason=data.get("finish_reason"),
        turn_context=(
            TurnContext(
                active_skill_id=turn_ctx.get("active_skill_id"),
                tools_mounted=turn_ctx.get("tools_mounted", []),
            )
            if turn_ctx
            else None
        ),
    )
