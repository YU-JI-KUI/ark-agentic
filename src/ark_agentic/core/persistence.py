"""
会话持久化 - JSONL 转录存储

参考: openclaw-main/src/config/sessions/transcript.ts, store.ts
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

# fcntl 仅在 Unix 系统上可用
if sys.platform != "win32":
    import fcntl
else:
    fcntl = None  # type: ignore

from .types import AgentMessage, AgentToolResult, MessageRole, ToolCall, ToolResultType

logger = logging.getLogger(__name__)


class RawJsonlValidationError(Exception):
    """JSONL 校验失败，用于 PUT .../raw 写回。"""

    def __init__(self, message: str, line_number: int | None = None):
        self.line_number = line_number
        super().__init__(message)


# ============ 常量 ============

SESSION_VERSION = 1
LOCK_TIMEOUT_MS = 10_000
LOCK_POLL_INTERVAL_MS = 25
LOCK_STALE_MS = 30_000


# ============ JSONL Entry 类型 ============


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


# ============ 消息序列化 ============


def serialize_tool_call(tc: ToolCall) -> dict[str, Any]:
    """序列化工具调用"""
    return {
        "id": tc.id,
        "type": "function",
        "function": {
            "name": tc.name,
            "arguments": json.dumps(tc.arguments, ensure_ascii=False),
        },
    }


def deserialize_tool_call(data: dict[str, Any]) -> ToolCall:
    """反序列化工具调用"""
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
    """序列化工具结果"""
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
    """反序列化工具结果"""
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
    """序列化 AgentMessage 为 JSONL 格式"""
    result: dict[str, Any] = {
        "role": msg.role.value,
    }

    # 内容
    if msg.content is not None:
        result["content"] = [{"type": "text", "text": msg.content}]

    # 工具调用
    if msg.tool_calls:
        result["tool_calls"] = [serialize_tool_call(tc) for tc in msg.tool_calls]

    # 工具结果
    if msg.tool_results:
        result["tool_results"] = [serialize_tool_result(tr) for tr in msg.tool_results]

    # 思考过程
    if msg.thinking:
        result["thinking"] = msg.thinking

    # 元数据
    if msg.metadata:
        result["metadata"] = msg.metadata

    return result


def deserialize_message(data: dict[str, Any]) -> AgentMessage:
    """反序列化 JSONL 格式为 AgentMessage"""
    role_str = data.get("role", "user")
    role = MessageRole(role_str)

    # 解析内容
    content = None
    content_data = data.get("content")
    if isinstance(content_data, str):
        content = content_data
    elif isinstance(content_data, list):
        for item in content_data:
            if isinstance(item, dict) and item.get("type") == "text":
                content = item.get("text", "")
                break

    # 解析工具调用
    tool_calls = None
    tc_data = data.get("tool_calls")
    if tc_data and isinstance(tc_data, list):
        tool_calls = [deserialize_tool_call(tc) for tc in tc_data]

    # 解析工具结果
    tool_results = None
    tr_data = data.get("tool_results")
    if tr_data and isinstance(tr_data, list):
        tool_results = [deserialize_tool_result(tr) for tr in tr_data]

    # 时间戳
    ts = data.get("timestamp")
    timestamp = datetime.fromtimestamp(ts / 1000) if ts else datetime.now()

    return AgentMessage(
        role=role,
        content=content,
        tool_calls=tool_calls,
        tool_results=tool_results,
        thinking=data.get("thinking"),
        timestamp=timestamp,
        metadata=data.get("metadata", {}),
    )


# ============ 文件锁 ============


class FileLock:
    """文件锁（跨平台）

    参考: openclaw-main/src/config/sessions/store.ts - withSessionStoreLock

    在 Windows 上使用文件存在性作为锁机制，
    在 Unix 上使用更可靠的 O_EXCL 文件创建。
    """

    def __init__(
        self,
        lock_path: str | Path,
        timeout_ms: int = LOCK_TIMEOUT_MS,
        poll_interval_ms: int = LOCK_POLL_INTERVAL_MS,
        stale_ms: int = LOCK_STALE_MS,
    ):
        self.lock_path = Path(lock_path)
        self.timeout_ms = timeout_ms
        self.poll_interval_ms = poll_interval_ms
        self.stale_ms = stale_ms
        self._fd: int | None = None
        self._file_handle: Any = None

    async def acquire(self) -> bool:
        """获取锁"""
        start_time = time.time() * 1000
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)

        while True:
            try:
                if sys.platform == "win32":
                    # Windows: 使用文件存在性检查 + 写锁
                    if self.lock_path.exists():
                        # 检查锁是否过期
                        now = time.time() * 1000
                        try:
                            stat = self.lock_path.stat()
                            age_ms = now - (stat.st_mtime * 1000)
                            if age_ms > self.stale_ms:
                                # 删除过期锁
                                self.lock_path.unlink(missing_ok=True)
                            else:
                                if now - start_time > self.timeout_ms:
                                    logger.warning(f"锁获取超时: {self.lock_path}")
                                    return False
                                await asyncio.sleep(self.poll_interval_ms / 1000)
                                continue
                        except (OSError, FileNotFoundError):
                            pass

                    # 尝试创建锁文件
                    lock_info = json.dumps(
                        {"pid": os.getpid(), "startedAt": int(time.time() * 1000)}
                    )
                    self._file_handle = open(self.lock_path, "x", encoding="utf-8")
                    self._file_handle.write(lock_info)
                    self._file_handle.flush()
                    return True
                else:
                    # Unix: 使用 O_EXCL 创建
                    self._fd = os.open(
                        str(self.lock_path),
                        os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                        0o600,
                    )
                    lock_info = json.dumps(
                        {"pid": os.getpid(), "startedAt": int(time.time() * 1000)}
                    )
                    os.write(self._fd, lock_info.encode())
                    return True

            except FileExistsError:
                # 锁已存在
                now = time.time() * 1000
                if now - start_time > self.timeout_ms:
                    logger.warning(f"锁获取超时: {self.lock_path}")
                    return False

                # 检查锁是否过期
                try:
                    stat = self.lock_path.stat()
                    age_ms = now - (stat.st_mtime * 1000)
                    if age_ms > self.stale_ms:
                        # 删除过期锁
                        self.lock_path.unlink(missing_ok=True)
                        continue
                except (OSError, FileNotFoundError):
                    pass

                # 等待后重试
                await asyncio.sleep(self.poll_interval_ms / 1000)
            except OSError as e:
                logger.error(f"锁获取失败: {e}")
                return False

    def release(self) -> None:
        """释放锁"""
        if self._fd is not None:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None

        if self._file_handle is not None:
            try:
                self._file_handle.close()
            except OSError:
                pass
            self._file_handle = None

        try:
            self.lock_path.unlink(missing_ok=True)
        except OSError:
            pass

    async def __aenter__(self) -> FileLock:
        if not await self.acquire():
            raise TimeoutError(f"无法获取锁: {self.lock_path}")
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.release()




# Backend-neutral DTO; lives in ``core.storage.entries`` so the data model is
# decoupled from the file backend. Re-export here for legacy import paths.
from .storage.entries import SessionStoreEntry  # noqa: E402,F401


