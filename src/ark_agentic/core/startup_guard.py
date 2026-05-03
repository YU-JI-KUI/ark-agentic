"""Startup deployment configuration guard.

启动期检测部署配置错配，例如多 worker 配进程内 Cache。
集成在 app.lifespan 内，错配时立即 raise，阻止启动。
"""

from __future__ import annotations

import os


class DeploymentConfigError(RuntimeError):
    """部署配置错配错误。包含可执行的修复建议。"""


def validate_deployment_config() -> None:
    """Validate environment-driven deployment config.

    检测项：
      - ``CACHE_TYPE=memory`` 与 ``WEB_CONCURRENCY > 1`` 不可组合 ——
        进程内 cache 在多 worker 下不一致，必须切到 Redis 或禁用 cache。
    """
    cache_type = os.environ.get("CACHE_TYPE", "memory").strip().lower()
    workers_raw = os.environ.get("WEB_CONCURRENCY", "1").strip()

    try:
        workers = int(workers_raw)
    except ValueError as e:
        raise DeploymentConfigError(
            f"WEB_CONCURRENCY must be an integer, got {workers_raw!r}"
        ) from e

    if cache_type == "memory" and workers > 1:
        raise DeploymentConfigError(
            f"In-process MemoryCache is not safe for multi-worker deployments "
            f"(CACHE_TYPE=memory, WEB_CONCURRENCY={workers}). "
            "Fix: set CACHE_TYPE=redis (recommended) or "
            "reduce WEB_CONCURRENCY to 1."
        )
