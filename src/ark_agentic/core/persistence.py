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

from .types import AgentMessage, AgentToolResult, MessageRole, ToolCall

logger = logging.getLogger(__name__)

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
    return {
        "tool_call_id": tr.tool_call_id,
        "content": content,
        "is_error": tr.is_error,
    }


def deserialize_tool_result(data: dict[str, Any]) -> AgentToolResult:
    """反序列化工具结果"""
    from .types import ToolResultType

    content = data.get("content", "")
    is_error = data.get("is_error", False)

    # 尝试解析 JSON 内容
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
        """初始化转录管理器

        Args:
            sessions_dir: 会话存储目录，默认为 ~/.ark_nav/sessions
        """
        if sessions_dir is None:
            sessions_dir = Path.home() / ".ark_nav" / "sessions"
        self.sessions_dir = Path(sessions_dir)
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

    def _get_session_file(self, session_id: str) -> Path:
        """获取会话文件路径"""
        return self.sessions_dir / f"{session_id}.jsonl"

    def _get_lock_path(self, session_id: str) -> Path:
        """获取锁文件路径"""
        return self.sessions_dir / f"{session_id}.jsonl.lock"

    async def ensure_header(self, session_id: str) -> None:
        """确保会话文件有头部"""
        session_file = self._get_session_file(session_id)
        if session_file.exists():
            return

        header = SessionHeader(
            id=session_id,
            timestamp=datetime.now().isoformat(),
            cwd=os.getcwd(),
        )

        session_file.parent.mkdir(parents=True, exist_ok=True)
        async with FileLock(self._get_lock_path(session_id)):
            with open(session_file, "w", encoding="utf-8") as f:
                f.write(json.dumps(header.to_dict(), ensure_ascii=False) + "\n")

    async def append_message(
        self,
        session_id: str,
        message: AgentMessage,
    ) -> None:
        """追加消息到转录文件"""
        await self.ensure_header(session_id)

        entry = MessageEntry(
            message=serialize_message(message),
            timestamp=int(message.timestamp.timestamp() * 1000),
        )

        async with FileLock(self._get_lock_path(session_id)):
            with open(self._get_session_file(session_id), "a", encoding="utf-8") as f:
                f.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")

    async def append_messages(
        self,
        session_id: str,
        messages: list[AgentMessage],
    ) -> None:
        """批量追加消息"""
        if not messages:
            return

        await self.ensure_header(session_id)

        lines: list[str] = []
        for msg in messages:
            entry = MessageEntry(
                message=serialize_message(msg),
                timestamp=int(msg.timestamp.timestamp() * 1000),
            )
            lines.append(json.dumps(entry.to_dict(), ensure_ascii=False))

        async with FileLock(self._get_lock_path(session_id)):
            with open(self._get_session_file(session_id), "a", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")

    def load_messages(self, session_id: str) -> list[AgentMessage]:
        """加载会话消息"""
        session_file = self._get_session_file(session_id)
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

    def load_header(self, session_id: str) -> SessionHeader | None:
        """加载会话头部"""
        session_file = self._get_session_file(session_id)
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
        message_count: int = 15,
        roles: list[str] | None = None,
    ) -> str | None:
        """获取最近的会话内容（用于摘要生成）

        参考: openclaw-main/src/hooks/bundled/session-memory/handler.ts
        """
        if roles is None:
            roles = ["user", "assistant"]

        messages = self.load_messages(session_id)

        # 过滤角色
        filtered: list[str] = []
        for msg in messages:
            if msg.role.value in roles and msg.content:
                # 跳过命令消息
                if not msg.content.startswith("/"):
                    filtered.append(f"{msg.role.value}: {msg.content}")

        if not filtered:
            return None

        # 取最近 N 条
        recent = filtered[-message_count:]
        return "\n".join(recent)

    def list_sessions(self) -> list[str]:
        """列出所有会话 ID"""
        sessions: list[str] = []
        for file in self.sessions_dir.glob("*.jsonl"):
            session_id = file.stem
            if not session_id.endswith(".lock"):
                sessions.append(session_id)
        return sessions

    def delete_session(self, session_id: str) -> bool:
        """删除会话文件"""
        session_file = self._get_session_file(session_id)
        lock_file = self._get_lock_path(session_id)

        deleted = False
        if session_file.exists():
            session_file.unlink()
            deleted = True
        if lock_file.exists():
            lock_file.unlink()

        return deleted

    def session_exists(self, session_id: str) -> bool:
        """检查会话是否存在"""
        return self._get_session_file(session_id).exists()


# ============ 会话元数据存储 ============


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
    active_skills: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

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
            "activeSkills": self.active_skills,
            "metadata": self.metadata,
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
            active_skills=data.get("activeSkills", []),
            metadata=data.get("metadata", {}),
        )


class SessionStore:
    """会话元数据存储

    管理 sessions.json 文件。

    参考: openclaw-main/src/config/sessions/store.ts
    """

    def __init__(self, store_path: str | Path | None = None):
        """初始化存储

        Args:
            store_path: 存储文件路径，默认为 ~/.ark_nav/sessions/sessions.json
        """
        if store_path is None:
            store_path = Path.home() / ".ark_nav" / "sessions" / "sessions.json"
        self.store_path = Path(store_path)
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, SessionStoreEntry] | None = None
        self._cache_time: float = 0
        self._cache_ttl: float = 45.0  # 45 秒缓存

    def _get_lock_path(self) -> Path:
        """获取锁文件路径"""
        return self.store_path.with_suffix(".json.lock")

    def _is_cache_valid(self) -> bool:
        """检查缓存是否有效"""
        if self._cache is None:
            return False
        return (time.time() - self._cache_time) <= self._cache_ttl

    def _invalidate_cache(self) -> None:
        """使缓存失效"""
        self._cache = None

    def load(self, skip_cache: bool = False) -> dict[str, SessionStoreEntry]:
        """加载会话存储"""
        if not skip_cache and self._is_cache_valid():
            return dict(self._cache)  # type: ignore

        store: dict[str, SessionStoreEntry] = {}

        if self.store_path.exists():
            try:
                with open(self.store_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for key, entry_data in data.items():
                        store[key] = SessionStoreEntry.from_dict(entry_data)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"加载会话存储失败: {e}")

        # 更新缓存
        self._cache = dict(store)
        self._cache_time = time.time()

        return store

    async def save(self, store: dict[str, SessionStoreEntry]) -> None:
        """保存会话存储"""
        self._invalidate_cache()
        self.store_path.parent.mkdir(parents=True, exist_ok=True)

        data = {key: entry.to_dict() for key, entry in store.items()}

        async with FileLock(self._get_lock_path()):
            with open(self.store_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

    async def update(
        self,
        session_key: str,
        entry: SessionStoreEntry,
    ) -> None:
        """更新单个会话条目"""
        async with FileLock(self._get_lock_path()):
            store = self.load(skip_cache=True)
            store[session_key] = entry
            self._invalidate_cache()

            data = {key: e.to_dict() for key, e in store.items()}
            with open(self.store_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

    def get(self, session_key: str) -> SessionStoreEntry | None:
        """获取会话条目"""
        store = self.load()
        return store.get(session_key)

    async def delete(self, session_key: str) -> bool:
        """删除会话条目"""
        async with FileLock(self._get_lock_path()):
            store = self.load(skip_cache=True)
            if session_key in store:
                del store[session_key]
                self._invalidate_cache()

                data = {key: e.to_dict() for key, e in store.items()}
                with open(self.store_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                return True
        return False

    def list_keys(self) -> list[str]:
        """列出所有会话键"""
        return list(self.load().keys())
