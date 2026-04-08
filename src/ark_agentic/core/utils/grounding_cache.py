"""Grounding 历史工具结果缓存。

进程内单例，TTL=20min（可配置），以 session_id 为 key，存储每次工具调用后
已归一化的 fact snapshot。在模型当前轮未调用任何工具时，可从历史缓存中恢复
事实语料，避免跨轮引用时误触发 UNGROUNDED retry。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Iterator


_DEFAULT_TTL_SEC: float = 20 * 60


@dataclass
class FactSnapshot:
    """单次工具调用轮次的已归一化 fact 文本快照。

    Attributes:
        tool_sources: 已归一化的工具输出文本，key 格式 ``tool_<name>``。
        created_at:   ``time.monotonic()`` 时间戳，用于 TTL 判断。
    """

    tool_sources: dict[str, str]
    created_at: float = field(default_factory=time.monotonic)


class GroundingCache:
    """进程内 Grounding 历史缓存，以 session_id 索引多条 FactSnapshot。

    线程安全性：Python GIL 保护 dict 操作，单进程场景足够；多进程部署时
    每个进程持有独立缓存（不跨进程共享），可接受。
    """

    def __init__(self, ttl_sec: float = _DEFAULT_TTL_SEC) -> None:
        self._ttl_sec = ttl_sec
        self._store: dict[str, list[FactSnapshot]] = {}

    def put(self, session_id: str, snapshot: FactSnapshot) -> None:
        """写入一条 snapshot；顺带清理过期条目。"""
        self.evict_expired()
        self._store.setdefault(session_id, []).append(snapshot)

    def get_recent(self, session_id: str) -> dict[str, str]:
        """返回 TTL 内全部 snapshot 合并后的 tool_sources。

        同名工具的多次结果用 ``\\n---\\n`` 拼接，保留最早到最新顺序，
        方便 grounding 做子串匹配时任一历史结果均可命中。
        空缓存 / 全过期 → 返回 ``{}``。
        """
        self.evict_expired()
        snapshots = self._store.get(session_id, [])
        if not snapshots:
            return {}

        merged: dict[str, list[str]] = {}
        for snap in snapshots:
            for key, text in snap.tool_sources.items():
                if text:
                    merged.setdefault(key, []).append(text)

        return {key: "\n---\n".join(chunks) for key, chunks in merged.items()}

    def evict_expired(self) -> None:
        """惰性清理全部 session 中 TTL 已过期的 snapshot。"""
        cutoff = time.monotonic() - self._ttl_sec
        empty_sessions: list[str] = []
        for session_id, snapshots in self._store.items():
            live = [s for s in snapshots if s.created_at >= cutoff]
            if live:
                self._store[session_id] = live
            else:
                empty_sessions.append(session_id)
        for sid in empty_sessions:
            del self._store[sid]

    def __iter__(self) -> Iterator[str]:
        return iter(self._store)

    def __len__(self) -> int:
        return sum(len(v) for v in self._store.values())


# 进程级单例；测试中可直接替换 grounding_cache._CACHE
_CACHE = GroundingCache()
