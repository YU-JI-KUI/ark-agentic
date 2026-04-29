"""
case_loader — 从 JSON 文件加载评测用例

返回 (文件级元数据, 用例列表) 两部分，由调用方分开使用。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# sevals/ 目录的绝对路径，供相对路径解析使用
_EVALS_DIR = Path(__file__).resolve().parent.parent


def load_cases(path: str | Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """加载 JSON 用例文件。

    Args:
        path: 相对于 sevals/ 目录的路径，或绝对路径。

    Returns:
        (meta, cases)
        meta  — 文件级字段：skill, agent, user_id
        cases — 用例列表，每个 case 含 id / description / input / expect_tools
    """
    p = Path(path)
    if not p.is_absolute():
        p = _EVALS_DIR / p

    with p.open(encoding="utf-8") as f:
        data = json.load(f)

    meta = {k: v for k, v in data.items() if k != "cases"}
    cases = data.get("cases", [])
    return meta, cases
