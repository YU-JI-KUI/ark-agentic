"""Jobs 数据目录解析。"""

from __future__ import annotations

import os
from pathlib import Path


def get_job_runs_base_dir() -> Path:
    """解析 job_runs 根目录。

    优先级: JOB_RUNS_DIR 环境变量 > data/ark_job_runs。
    """
    return Path(os.getenv("JOB_RUNS_DIR") or "data/ark_job_runs")
