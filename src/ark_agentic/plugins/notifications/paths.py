"""Notifications 数据目录解析。"""

from __future__ import annotations

import os
from pathlib import Path


def get_notifications_base_dir() -> Path:
    """解析 notifications 根目录。

    优先级: NOTIFICATIONS_DIR 环境变量 > data/ark_notifications。
    """
    return Path(os.getenv("NOTIFICATIONS_DIR") or "data/ark_notifications")
