"""Flow 框架级回调实现。

persist_flow_context — after_agent hook: 持久化 _flow_context 到 active_tasks.json

待恢复任务检测已移入 BaseFlowEvaluator.execute()，仅在 SKILL 被实际调用时触发，
避免无关问题被前置拦截。

使用方式:
    from ark_agentic.core.flow.callbacks import FlowCallbacks
    from ark_agentic.core.callbacks import RunnerCallbacks

    fc = FlowCallbacks(sessions_dir=sessions_dir)
    callbacks = RunnerCallbacks(after_agent=[fc.persist_flow_context])
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


class FlowCallbacks:
    """after_agent flow hook，注入到 RunnerCallbacks。

    使用:
        fc = FlowCallbacks(sessions_dir=sessions_dir)
        RunnerCallbacks(after_agent=[fc.persist_flow_context])
    """

    def __init__(self, sessions_dir: Path, ttl_hours: int = 72) -> None:
        self._sessions_dir = sessions_dir
        self._ttl_hours = ttl_hours

    # ── after_agent ───────────────────────────────────────────────────────────

    async def persist_flow_context(
        self,
        ctx: CallbackContext,
        *,
        response: AgentMessage,
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
            current_stage_id = restorable["current_stage"]

            # checkpoint 检查：只在最后完成的阶段标记了 checkpoint=True 时写盘。
            # 流程已全部完成（__completed__）时始终写盘以触发 TaskRegistry 清理。
            if current_stage_id != "__completed__":
                completed_ids = [
                    s.id for s in evaluator.stages
                    if restorable["stages"].get(s.id, {}).get("status") == "completed"
                ]
                if not completed_ids:
                    return None
                last_completed = next(s for s in evaluator.stages if s.id == completed_ids[-1])
                if not last_completed.checkpoint:
                    logger.debug(
                        "Skipping persist: stage '%s' is not a checkpoint", last_completed.id
                    )
                    return None

            registry = TaskRegistry(base_dir=self._sessions_dir)
            registry.upsert(
                user_id=str(user_id),
                flow_id=flow_ctx["flow_id"],
                skill_name=skill_name,
                current_stage=current_stage_id,
                last_session_id=session.session_id,
                flow_context_snapshot=restorable,
                resume_ttl_hours=self._ttl_hours,
            )
            logger.debug(
                "Persisted flow '%s' stage='%s' for user %s",
                flow_ctx["flow_id"], current_stage_id, user_id,
            )
        except Exception:
            logger.warning("Failed to persist flow context", exc_info=True)

        return None
