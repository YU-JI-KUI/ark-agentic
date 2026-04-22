"""Session state 通用操作。

抽出自 runner.py 和 flow/callbacks.py 中重复的 _apply_state_delta 实现，
避免逻辑分叉。支持点路径（dot-path）的深度合并。
"""

from __future__ import annotations

from typing import Any


def apply_delta(state: dict[str, Any], key: str, value: Any) -> None:
    """将单个 dot-path 键值对写入 state。

    普通 key           → state[key] = value（浅覆盖）
    点路径 key         → 逐层 setdefault({}) 后赋值，不整体替换父对象。
    """
    if "." in key:
        parts = key.split(".")
        obj = state
        for part in parts[:-1]:
            if not isinstance(obj.get(part), dict):
                obj[part] = {}
            obj = obj[part]
        obj[parts[-1]] = value
    else:
        state[key] = value


def apply_state_delta(state: dict[str, Any], delta: dict[str, Any]) -> None:
    """批量应用 delta 到 state。"""
    for key, value in delta.items():
        apply_delta(state, key, value)
