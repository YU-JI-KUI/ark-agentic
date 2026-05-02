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

from .types import AgentMessage, AgentToolResult, MessageRole, ToolCall, ToolResultType, TurnContext

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

    if msg.finish_reason is not None:
        result["finish_reason"] = msg.finish_reason
    if msg.turn_context is not None:
        result["turn_context"] = {
            "active_skill_id": msg.turn_context.active_skill_id,
            "tools_mounted": msg.turn_context.tools_mounted,
        }

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


# ============ 会话转录管理 ============


class TranscriptManager:
    """会话转录管理器

    管理 JSONL 格式的会话转录文件。

    参考: openclaw-main/src/config/sessions/transcript.ts
    """

    def __init__(
        self,
        sessions_dir: str | Path | None = None,
    ):
        if sessions_dir is None:
            sessions_dir = Path.home() / ".ark_nav" / "sessions"
        self.sessions_dir = Path(sessions_dir)
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

    def _get_user_dir(self, user_id: str) -> Path:
        return self.sessions_dir / user_id

    def _get_session_file(self, session_id: str, user_id: str) -> Path:
        return self._get_user_dir(user_id) / f"{session_id}.jsonl"

    def _get_lock_path(self, session_id: str, user_id: str) -> Path:
        return self._get_user_dir(user_id) / f"{session_id}.jsonl.lock"

    @staticmethod
    def _ensure_trailing_newline(filepath: Path) -> None:
        """Guard against corrupted JSONL: ensure file ends with newline before append."""
        if filepath.exists() and filepath.stat().st_size > 0:
            with open(filepath, "rb") as rf:
                rf.seek(-1, 2)
                if rf.read(1) != b"\n":
                    with open(filepath, "a", encoding="utf-8") as f:
                        f.write("\n")

    async def ensure_header(self, session_id: str, user_id: str) -> None:
        session_file = self._get_session_file(session_id, user_id)
        if session_file.exists():
            return

        header = SessionHeader(
            id=session_id,
            timestamp=datetime.now().isoformat(),
            cwd=os.getcwd(),
        )

        session_file.parent.mkdir(parents=True, exist_ok=True)
        async with FileLock(self._get_lock_path(session_id, user_id)):
            with open(session_file, "w", encoding="utf-8") as f:
                f.write(json.dumps(header.to_dict(), ensure_ascii=False) + "\n")

    async def append_message(
        self,
        session_id: str,
        user_id: str,
        message: AgentMessage,
    ) -> None:
        await self.ensure_header(session_id, user_id)

        entry = MessageEntry(
            message=serialize_message(message),
            timestamp=int(message.timestamp.timestamp() * 1000),
        )

        async with FileLock(self._get_lock_path(session_id, user_id)):
            filepath = self._get_session_file(session_id, user_id)
            self._ensure_trailing_newline(filepath)
            with open(filepath, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")

    async def append_messages(
        self,
        session_id: str,
        user_id: str,
        messages: list[AgentMessage],
    ) -> None:
        if not messages:
            return

        await self.ensure_header(session_id, user_id)

        lines: list[str] = []
        for msg in messages:
            entry = MessageEntry(
                message=serialize_message(msg),
                timestamp=int(msg.timestamp.timestamp() * 1000),
            )
            lines.append(json.dumps(entry.to_dict(), ensure_ascii=False))

        async with FileLock(self._get_lock_path(session_id, user_id)):
            filepath = self._get_session_file(session_id, user_id)
            self._ensure_trailing_newline(filepath)
            with open(filepath, "a", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")

    def load_messages(self, session_id: str, user_id: str) -> list[AgentMessage]:
        session_file = self._get_session_file(session_id, user_id)
        if not session_file.exists():
            return []

        messages: list[AgentMessage] = []
        with open(session_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    if data.get("type") == "message":
                        msg_data = data.get("message", {})
                        messages.append(deserialize_message(msg_data))
                except json.JSONDecodeError:
                    logger.warning(f"跳过无效 JSON 行: {line[:50]}...")

        return messages

    def load_header(self, session_id: str, user_id: str) -> SessionHeader | None:
        session_file = self._get_session_file(session_id, user_id)
        if not session_file.exists():
            return None

        with open(session_file, "r", encoding="utf-8") as f:
            first_line = f.readline().strip()
            if first_line:
                try:
                    data = json.loads(first_line)
                    if data.get("type") == "session":
                        return SessionHeader.from_dict(data)
                except json.JSONDecodeError:
                    pass
        return None

    def get_recent_content(
        self,
        session_id: str,
        user_id: str,
        message_count: int = 15,
        roles: list[str] | None = None,
    ) -> str | None:
        if roles is None:
            roles = ["user", "assistant"]

        messages = self.load_messages(session_id, user_id)

        filtered: list[str] = []
        for msg in messages:
            if msg.role.value in roles and msg.content:
                if not msg.content.startswith("/"):
                    filtered.append(f"{msg.role.value}: {msg.content}")

        if not filtered:
            return None

        recent = filtered[-message_count:]
        return "\n".join(recent)

    def list_sessions(self, user_id: str) -> list[str]:
        """列出指定用户的所有会话 ID"""
        user_dir = self._get_user_dir(user_id)
        if not user_dir.exists():
            return []
        sessions: list[str] = []
        for file in user_dir.glob("*.jsonl"):
            session_id = file.stem
            if not session_id.endswith(".lock"):
                sessions.append(session_id)
        return sessions

    def list_all_sessions(self) -> list[tuple[str, str]]:
        """列出所有用户的所有会话，返回 (user_id, session_id) 列表（admin 用途）"""
        results: list[tuple[str, str]] = []
        if not self.sessions_dir.exists():
            return results
        for user_dir in self.sessions_dir.iterdir():
            if not user_dir.is_dir():
                continue
            user_id = user_dir.name
            for file in user_dir.glob("*.jsonl"):
                sid = file.stem
                if not sid.endswith(".lock"):
                    results.append((user_id, sid))
        return results

    def delete_session(self, session_id: str, user_id: str) -> bool:
        session_file = self._get_session_file(session_id, user_id)
        lock_file = self._get_lock_path(session_id, user_id)

        deleted = False
        if session_file.exists():
            session_file.unlink()
            deleted = True
        if lock_file.exists():
            lock_file.unlink()

        return deleted

    def session_exists(self, session_id: str, user_id: str) -> bool:
        return self._get_session_file(session_id, user_id).exists()

    def read_raw(self, session_id: str, user_id: str) -> str | None:
        session_file = self._get_session_file(session_id, user_id)
        if not session_file.exists():
            return None
        return session_file.read_text(encoding="utf-8")

    async def write_raw(self, session_id: str, user_id: str, content: str) -> None:
        """校验并全量写入会话 JSONL 文件。持 FileLock。校验失败抛出 RawJsonlValidationError。"""
        lines = [line for line in content.splitlines() if line.strip()]
        if not lines:
            raise RawJsonlValidationError("至少需要一行（session header）", line_number=1)
        try:
            first = json.loads(lines[0])
        except json.JSONDecodeError as e:
            raise RawJsonlValidationError(f"首行非法 JSON: {e}", line_number=1) from e
        if first.get("type") != "session":
            raise RawJsonlValidationError("首行 type 必须为 session", line_number=1)
        header_id = (first.get("id") or "").strip()
        if header_id != session_id.strip():
            raise RawJsonlValidationError(
                f"首行 id 与 URL session_id 不一致: {header_id!r} vs {session_id!r}",
                line_number=1,
            )
        for i, line in enumerate(lines[1:], start=2):
            try:
                data = json.loads(line)
            except json.JSONDecodeError as e:
                raise RawJsonlValidationError(f"第 {i} 行非法 JSON: {e}", line_number=i) from e
            if data.get("type") != "message":
                raise RawJsonlValidationError(
                    f"第 {i} 行 type 必须为 message",
                    line_number=i,
                )
            if "message" not in data or not isinstance(data["message"], dict):
                raise RawJsonlValidationError(
                    f"第 {i} 行必须含 message 对象",
                    line_number=i,
                )
        session_file = self._get_session_file(session_id, user_id)
        session_file.parent.mkdir(parents=True, exist_ok=True)
        payload = content if content.endswith("\n") else content + "\n"
        async with FileLock(self._get_lock_path(session_id, user_id)):
            session_file.write_text(payload, encoding="utf-8")


@dataclass
class SessionStoreEntry:
    """会话存储条目

    参考: openclaw-main/src/config/sessions/types.ts - SessionEntry
    """

    session_id: str
    updated_at: int  # 毫秒时间戳
    session_file: str | None = None
    model: str = "Qwen3-80B-Instruct"
    provider: str = "ark"
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    compaction_count: int = 0
    active_skill_ids: list[str] = field(default_factory=list)
    state: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sessionId": self.session_id,
            "updatedAt": self.updated_at,
            "sessionFile": self.session_file,
            "model": self.model,
            "provider": self.provider,
            "inputTokens": self.prompt_tokens,
            "outputTokens": self.completion_tokens,
            "totalTokens": self.total_tokens,
            "compactionCount": self.compaction_count,
            "activeSkillIds": self.active_skill_ids,
            "state": self.state,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SessionStoreEntry:
        return cls(
            session_id=data.get("sessionId", ""),
            updated_at=data.get("updatedAt", 0),
            session_file=data.get("sessionFile"),
            model=data.get("model", "Qwen3-80B-Instruct"),
            provider=data.get("provider", "ark"),
            prompt_tokens=data.get("inputTokens", 0),
            completion_tokens=data.get("outputTokens", 0),
            total_tokens=data.get("totalTokens", 0),
            compaction_count=data.get("compactionCount", 0),
            active_skill_ids=data.get("activeSkillIds", []),
            state=data.get("state", {}),
        )


class SessionStore:
    """会话元数据存储（per-user sessions.json）

    参考: openclaw-main/src/config/sessions/store.ts
    """

    def __init__(self, sessions_dir: str | Path | None = None):
        if sessions_dir is None:
            sessions_dir = Path.home() / ".ark_nav" / "sessions"
        self.sessions_dir = Path(sessions_dir)
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self._caches: dict[str, dict[str, SessionStoreEntry]] = {}
        self._cache_times: dict[str, float] = {}
        self._cache_ttl: float = 45.0

    def _store_path(self, user_id: str) -> Path:
        return self.sessions_dir / user_id / "sessions.json"

    def _get_lock_path(self, user_id: str) -> Path:
        return self.sessions_dir / user_id / "sessions.json.lock"

    def _is_cache_valid(self, user_id: str) -> bool:
        if user_id not in self._caches:
            return False
        return (time.time() - self._cache_times.get(user_id, 0)) <= self._cache_ttl

    def _invalidate_cache(self, user_id: str) -> None:
        self._caches.pop(user_id, None)
        self._cache_times.pop(user_id, None)

    def load(self, user_id: str, skip_cache: bool = False) -> dict[str, SessionStoreEntry]:
        if not skip_cache and self._is_cache_valid(user_id):
            return dict(self._caches[user_id])

        store: dict[str, SessionStoreEntry] = {}
        sp = self._store_path(user_id)

        if sp.exists():
            try:
                with open(sp, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for key, entry_data in data.items():
                        store[key] = SessionStoreEntry.from_dict(entry_data)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"加载会话存储失败: {e}")

        self._caches[user_id] = dict(store)
        self._cache_times[user_id] = time.time()

        return store

    async def save(self, user_id: str, store: dict[str, SessionStoreEntry]) -> None:
        self._invalidate_cache(user_id)
        sp = self._store_path(user_id)
        sp.parent.mkdir(parents=True, exist_ok=True)

        data = {key: entry.to_dict() for key, entry in store.items()}

        async with FileLock(self._get_lock_path(user_id)):
            with open(sp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

    async def update(
        self,
        user_id: str,
        session_key: str,
        entry: SessionStoreEntry,
    ) -> None:
        sp = self._store_path(user_id)
        sp.parent.mkdir(parents=True, exist_ok=True)
        async with FileLock(self._get_lock_path(user_id)):
            store = self.load(user_id, skip_cache=True)
            store[session_key] = entry
            self._invalidate_cache(user_id)

            data = {key: e.to_dict() for key, e in store.items()}
            with open(sp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

    def get(self, user_id: str, session_key: str) -> SessionStoreEntry | None:
        store = self.load(user_id)
        return store.get(session_key)

    async def delete(self, user_id: str, session_key: str) -> bool:
        async with FileLock(self._get_lock_path(user_id)):
            store = self.load(user_id, skip_cache=True)
            if session_key in store:
                del store[session_key]
                self._invalidate_cache(user_id)

                data = {key: e.to_dict() for key, e in store.items()}
                sp = self._store_path(user_id)
                with open(sp, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                return True
        return False

    def list_keys(self, user_id: str) -> list[str]:
        return list(self.load(user_id).keys())
