"""TaskRegistry — active_tasks.json 读写 + TTL 清理。

文件路径: {base_dir}/{user_id}/active_tasks.json

格式:
{
  "active_tasks": [
    {
      "flow_id": "uuid",
      "skill_name": "withdraw_money_flow",
      "current_stage": "plan_confirm",
      "last_session_id": "session_xxx",
      "updated_at": 1744444900000,
      "resume_ttl_hours": 72,
      "flow_context_snapshot": { ... }
    }
  ]
}
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class TaskRegistry:
    """active_tasks.json 读写管理器。"""

    DEFAULT_TTL_HOURS = 72

    def __init__(self, base_dir: str | Path) -> None:
        self._base_dir = Path(base_dir)

    # ── 公共 API ──────────────────────────────────────────────────────────────

    def upsert(
        self,
        *,
        user_id: str,
        flow_id: str,
        skill_name: str,
        current_stage: str,
        last_session_id: str,
        flow_context_snapshot: dict[str, Any],
        task_name: str | None = None,
        resume_ttl_hours: int = DEFAULT_TTL_HOURS,
    ) -> None:
        """新增或更新一条 active task 记录。

        task_name 可选；未传时记录中不写该字段，读取方（pending task 渲染）
        会在缺失时 fallback 到 skill_name，保持对旧记录的读兼容。
        """
        tasks = self._load(user_id)
        now_ms = int(time.time() * 1000)

        existing = next((t for t in tasks if t["flow_id"] == flow_id), None)
        record: dict[str, Any] = {
            "flow_id": flow_id,
            "skill_name": skill_name,
            "current_stage": current_stage,
            "last_session_id": last_session_id,
            "updated_at": now_ms,
            "resume_ttl_hours": resume_ttl_hours,
            "flow_context_snapshot": flow_context_snapshot,
        }
        if task_name:
            record["task_name"] = task_name
        if existing:
            tasks[tasks.index(existing)] = record
        else:
            tasks.append(record)

        if current_stage == "__completed__":
            tasks = [t for t in tasks if t["flow_id"] != flow_id]

        self._save(user_id, tasks)

    def generate_flow_id(self, user_id: str) -> str:
        """生成 `YYMMDD-HHHH` 格式的短 flow_id，per-user 查重。

        日期前缀让日志/人工排查更直观；4 位 hex 后缀在 per-user 活跃任务集合中
        碰撞概率几乎为 0（65536 空间 vs 典型数个活跃任务）。
        极低概率碰撞时重试最多 8 次，兜底扩至 8 位 hex。
        """
        import uuid
        from datetime import datetime

        date_prefix = datetime.now().strftime("%y%m%d")
        existing = {t["flow_id"] for t in self._load(user_id)}
        for _ in range(8):
            candidate = f"{date_prefix}-{uuid.uuid4().hex[:4]}"
            if candidate not in existing:
                return candidate
        return f"{date_prefix}-{uuid.uuid4().hex[:8]}"

    def get(self, user_id: str, flow_id: str) -> dict[str, Any] | None:
        """按 flow_id 查询单条记录（不过滤 TTL）。"""
        tasks = self._load(user_id)
        return next((t for t in tasks if t["flow_id"] == flow_id), None)

    def list_active(self, user_id: str, ttl_hours: int = DEFAULT_TTL_HOURS) -> list[dict[str, Any]]:
        """列出未过期的 active tasks（已完成的自动过滤）。"""
        tasks = self._load(user_id)
        now_ms = int(time.time() * 1000)
        cutoff_ms = ttl_hours * 3600 * 1000
        return [
            t for t in tasks
            if t.get("current_stage") != "__completed__"
            and (now_ms - t.get("updated_at", 0)) < cutoff_ms
        ]

    def remove(self, user_id: str, flow_id: str) -> None:
        tasks = self._load(user_id)
        tasks = [t for t in tasks if t["flow_id"] != flow_id]
        self._save(user_id, tasks)

    # ── 内部 IO ───────────────────────────────────────────────────────────────

    def _registry_path(self, user_id: str) -> Path:
        return self._base_dir / str(user_id) / "active_tasks.json"

    def _load(self, user_id: str) -> list[dict[str, Any]]:
        path = self._registry_path(user_id)
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data.get("active_tasks", [])
        except Exception as e:
            logger.warning("Failed to load active_tasks for user %s: %s", user_id, e)
            return []

    def _save(self, user_id: str, tasks: list[dict[str, Any]]) -> None:
        path = self._registry_path(user_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            path.write_text(
                json.dumps({"active_tasks": tasks}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.error("Failed to save active_tasks for user %s: %s", user_id, e)
