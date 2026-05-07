"""Job 系统 — 主动服务定时任务调度

模块分层:
  - BaseJob / JobMeta / JobRunStats / ProactiveServiceJob / UserShardScanner
    : 纯 Python 抽象,无需 apscheduler,任何场景都可导入
  - JobManager / get_job_manager / set_job_manager
    : 依赖 apscheduler,仅在已安装 ``ark-agentic[server]`` 时可用
"""

from .base import BaseJob, JobMeta, JobRunStats
from .factory import build_job_run_repository
from .paths import get_job_runs_base_dir
from .protocol import JobRunRepository
from .scanner import UserShardScanner
from .proactive_service import ProactiveServiceJob

__all__ = [
    "BaseJob",
    "JobMeta",
    "JobRunStats",
    "JobRunRepository",
    "UserShardScanner",
    "ProactiveServiceJob",
    "build_job_run_repository",
    "get_job_runs_base_dir",
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
