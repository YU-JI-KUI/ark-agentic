"""Flow 框架级回调实现。

persist_flow_context — after_agent hook: 持久化 _flow_context 到 active_tasks.json
inject_flow_hint    — before_agent hook: 检查未完成任务并注入系统提示

使用方式:
    from ark_agentic.core.flow.callbacks import make_flow_callbacks
    from ark_agentic.core.callbacks import RunnerCallbacks, merge_runner_callbacks

    flow_callbacks = make_flow_callbacks(sessions_dir=sessions_dir)
    callbacks = merge_runner_callbacks(business_callbacks, flow_callbacks)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ..callbacks import CallbackContext, CallbackResult
from ..types import AgentMessage
from .base_evaluator import FlowEvaluatorRegistry
from .task_registry import TaskRegistry

logger = logging.getLogger(__name__)


def make_flow_callbacks(
    sessions_dir: str | Path,
    ttl_hours: int = 72,
) -> "FlowCallbacks":
    """工厂函数，返回绑定了 sessions_dir 的 FlowCallbacks。"""
    return FlowCallbacks(sessions_dir=Path(sessions_dir), ttl_hours=ttl_hours)


class FlowCallbacks:
    """封装 before_agent / after_agent 两个 flow hook，注入到 RunnerCallbacks。

    使用:
        fc = FlowCallbacks(sessions_dir=sessions_dir)
        RunnerCallbacks(before_agent=[fc.inject_flow_hint], after_agent=[fc.persist_flow_context])
    """

    def __init__(self, sessions_dir: Path, ttl_hours: int = 72) -> None:
        self._sessions_dir = sessions_dir
        self._ttl_hours = ttl_hours

    # ── before_agent ──────────────────────────────────────────────────────────

    async def inject_flow_hint(self, ctx: CallbackContext, **kwargs: Any) -> CallbackResult | None:
        """检查用户的 active tasks，将提示注入 session state 供 _build_system_prompt 读取。"""
        user_id = ctx.session.state.get("user:id")
        if not user_id:
            logger.debug("No user id found, skipping inject flow hint")
            return None

        registry = TaskRegistry(base_dir=self._sessions_dir)
        active = registry.list_active(str(user_id), ttl_hours=self._ttl_hours)
        logger.debug("Active tasks: %s", active)
        if not active:
            # 清除上一次注入的 hint
            return CallbackResult(context_updates={"_flow_hint": ""})

        if len(active) == 1:
            task = active[0]
            hint = (
                f"[系统提示] 检测到用户有 1 个未完成任务：\n"
                f"  · 「{task['skill_name']}」— 当前在「{task['current_stage']}」阶段"
                f"（flow_id={task['flow_id']}）\n\n"
                f"请向用户展示该任务，等待用户明确答复后再操作：\n"
                f"  继续      → resume_task(flow_id=\"{task['flow_id']}\", action=\"resume\")\n"
                f"  废弃      → resume_task(flow_id=\"{task['flow_id']}\", action=\"discard\")\n"
                f"  重新开始  → resume_task(flow_id=\"{task['flow_id']}\", action=\"discard\")，然后重新发起流程\n\n"
                f"⚠️ 严禁未得到用户答复前直接调用 resume_task。"
            )
        else:
            items = "\n".join(
                f"  {i + 1}. 「{t['skill_name']}」— {t['current_stage']} 阶段（flow_id={t['flow_id']}）"
                for i, t in enumerate(active)
            )
            hint = (
                f"[系统提示] 检测到用户有 {len(active)} 个未完成任务：\n{items}\n\n"
                f"请先向用户展示列表，请其指明要操作哪一个；\n"
                f"用户选定后，再询问意向（继续 / 废弃 / 重新开始），等待明确答复后再调用对应的 resume_task：\n"
                f"  继续      → resume_task(flow_id=<选定的 flow_id>, action=\"resume\")\n"
                f"  废弃      → resume_task(flow_id=<选定的 flow_id>, action=\"discard\")\n"
                f"  重新开始  → resume_task(flow_id=<选定的 flow_id>, action=\"discard\")，然后重新发起流程\n\n"
                f"⚠️ 严禁未得到用户答复前直接调用 resume_task。"
            )

        return CallbackResult(
            context_updates={
                "_flow_hint": hint,
                "_pending_flow_ids": [t["flow_id"] for t in active],
            }
        )

    # ── after_agent ───────────────────────────────────────────────────────────

    async def persist_flow_context(
        self,
        ctx: CallbackContext,
        *,
        response: AgentMessage,
        **kwargs: Any,
    ) -> CallbackResult | None:
        """持久化 _flow_context 到 active_tasks.json。"""
        session = ctx.session
        flow_ctx = session.state.get("_flow_context")
        if not flow_ctx or not flow_ctx.get("flow_id"):
            return None

        user_id = session.state.get("user:id")
        if not user_id:
            return None

        skill_name = flow_ctx.get("skill_name", "")
        evaluator = FlowEvaluatorRegistry.get(skill_name)
        if not evaluator:
            logger.debug("No evaluator registered for skill '%s', skipping persist", skill_name)
            return None

        try:
            restorable = evaluator.get_restorable_state(flow_ctx)
            registry = TaskRegistry(base_dir=self._sessions_dir)
            registry.upsert(
                user_id=str(user_id),
                flow_id=flow_ctx["flow_id"],
                skill_name=skill_name,
                current_stage=restorable["current_stage"],
                last_session_id=session.session_id,
                flow_context_snapshot=restorable,
                resume_ttl_hours=self._ttl_hours,
            )
            logger.debug(
                "Persisted flow '%s' stage='%s' for user %s",
                flow_ctx["flow_id"], restorable["current_stage"], user_id,
            )
        except Exception:
            logger.warning("Failed to persist flow context", exc_info=True)

        return None
