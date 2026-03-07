"""
A2UI 模板渲染（与业务无关）

从模板目录按 card_type 读取 template.json，注入 surfaceId，合并 data，返回完整 A2UI 负载。
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any


def render_from_template(
    template_root: str | Path,
    card_type: str,
    data: dict[str, Any],
    session_id: str = "",
) -> dict[str, Any]:
    """
    从 template_root/{card_type}/template.json 读入 A2UI 模板，
    注入 surfaceId，用 data 覆盖模板中的 data，返回完整 A2UI 负载。

    Args:
        template_root: 模板根目录（绝对路径或可解析路径）。
        card_type: 卡片类型，对应子目录名。
        data: 扁平 data，合并时覆盖模板内 data。
        session_id: 用于生成 surfaceId。

    Returns:
        完整 A2UI 负载（event, version, surfaceId, rootComponentId, components, data, ...）。

    Raises:
        FileNotFoundError: 模板文件不存在。
        json.JSONDecodeError: 模板不是合法 JSON。
    """
    root = Path(template_root)
    path = root / card_type / "template.json"
    if not path.is_file():
        raise FileNotFoundError(f"模板不存在: {card_type} (路径: {path})")

    raw = path.read_text(encoding="utf-8")
    payload = json.loads(raw)

    surface_id = f"{card_type}-{(session_id or '')[:8]}-{uuid.uuid4().hex[:6]}"
    payload["surfaceId"] = surface_id
    base = dict(payload.get("data") or {})
    base.update(data)
    payload["data"] = base

    return payload
