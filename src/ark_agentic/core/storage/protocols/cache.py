"""Cache Protocol — generic KV with optional TTL."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class Cache(Protocol):
    """Generic KV with optional TTL.

    **PR1 范围内本接口无业务调用者** —— 为 PR2 的 session/memory 缓存层预留。
    PR1 只验证 MemoryCache 行为 + startup guard 检测多 worker 不可用 memory。

    多 worker 部署不可使用 in-process MemoryCache —— validate_deployment_config()
    检测此组合并 raise。
    """

    async def get(self, key: str) -> Any | None:
        ...

    async def set(
        self,
        key: str,
        value: Any,
        ttl_seconds: float | None = None,
    ) -> None:
        """fractional seconds 允许（用于测试）；Redis 实现下整秒 SETEX，亚秒 PEXPIRE。"""
        ...

    async def delete(self, key: str) -> None:
        ...

    async def exists(self, key: str) -> bool:
        ...
