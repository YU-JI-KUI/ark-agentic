"""Job 系统 — 主动服务定时任务调度

模块分层:
  - BaseJob / JobMeta / JobRunStats / ProactiveServiceJob / UserShardScanner
    : 纯 Python 抽象,无需 apscheduler,任何场景都可导入
  - JobManager / get_job_manager / set_job_manager
    : 依赖 apscheduler,仅在已安装 `ark-agentic[server]` 时可用
  - ProactiveJobBindings / build_* / apply_*
    : runner 解耦桥,任何场景都可导入
"""

from .base import BaseJob, JobMeta, JobRunStats
from .scanner import UserShardScanner
from .proactive_service import ProactiveServiceJob
from .bindings import (
    ProactiveJobBindings,
    apply_proactive_job_bindings,
    build_proactive_job_bindings,
)

__all__ = [
    "BaseJob",
    "JobMeta",
    "JobRunStats",
    "UserShardScanner",
    "ProactiveServiceJob",
    "ProactiveJobBindings",
    "build_proactive_job_bindings",
    "apply_proactive_job_bindings",
]

# JobManager 需要 apscheduler,仅在已安装时导出
try:
    from .manager import JobManager, get_job_manager, set_job_manager
    __all__ += ["JobManager", "get_job_manager", "set_job_manager"]
except ImportError as _e:
    import logging as _logging
    _logging.getLogger(__name__).debug(
        "JobManager unavailable — install `ark-agentic[server]` (apscheduler): %s",
        _e,
    )
