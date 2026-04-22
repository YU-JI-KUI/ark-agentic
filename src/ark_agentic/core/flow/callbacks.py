"""Flow 框架级回调实现。

三个 Hook 构成完整的 Flow 生命周期管理：

  before_model_flow_eval — before_model hook:
    每轮 LLM 调用前自动运行评估器，将当前阶段状态注入到系统提示词中。
    处理 pending task 检测（替代原 evaluator.execute() 中的逻辑）。

  after_tool_auto_commit — after_tool hook:
    工具执行后自动提交只含 source='tool' 字段且数据已就绪的阶段。

  persist_flow_context — after_agent hook:
    持久化 _flow_context 到 active_tasks.json。

使用方式:
    from ark_agentic.core.flow.callbacks import FlowCallbacks
    from ark_agentic.core.callbacks import RunnerCallbacks

    fc = FlowCallbacks(sessions_dir=sessions_dir)
    callbacks = RunnerCallbacks(
        before_model=[fc.before_model_flow_eval],
        after_tool=[fc.after_tool_auto_commit],
        after_agent=[fc.persist_flow_context],
    )
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from ..callbacks import CallbackContext, CallbackResult
from ..state_utils import apply_delta, apply_state_delta
from ..types import AgentMessage
from .base_evaluator import BaseFlowEvaluator, FlowEvalResult, FlowEvaluatorRegistry, StageDefinition
from .task_registry import TaskRegistry

logger = logging.getLogger(__name__)


# ── 消息注入辅助 ──────────────────────────────────────────────────────────────


def _append_to_system_message(messages: list[dict[str, Any]], content: str) -> None:
    """将 content 追加到第一个 system message 末尾。若不存在则插入。"""
    for i, msg in enumerate(messages):
        if msg.get("role") == "system":
            messages[i] = {**msg, "content": msg["content"] + f"\n\n---\n{content}"}
            return
    messages.insert(0, {"role": "system", "content": content})


# ── 格式化辅助 ────────────────────────────────────────────────────────────────


def _format_pending_task(task: dict[str, Any]) -> str:
    """格式化 pending task 注入内容（提示词层面）。"""
    return (
        f"## ⚠️ 检测到未完成的流程任务\n\n"
        f"用户有未完成的「{task['skill_name']}」任务（当前阶段：{task['current_stage']}）。\n"
        f"请先向用户说明情况，等待用户明确答复：\n"
        f"- 继续任务 → 调用 resume_task(flow_id=\"{task['flow_id']}\", action=\"resume\")\n"
        f"- 放弃任务 → 调用 resume_task(flow_id=\"{task['flow_id']}\", action=\"discard\")，"
        f"然后重新发起流程\n\n"
        f"⚠️ 严禁未得到用户明确答复前直接调用 resume_task。"
    )


def _format_flow_status(result: FlowEvalResult, evaluator: BaseFlowEvaluator) -> str:
    """格式化当前阶段状态注入内容（提示词层面）。"""
    if result.is_done:
        return f"## 流程状态：{evaluator.skill_name}\n\n所有阶段已完成，流程结束。"

    stage = result.current_stage
    assert stage is not None

    lines = [
        f"## 当前流程状态：{evaluator.skill_name}",
        f"",
        f"- **当前阶段**：{stage.name}（{stage.id}）",
        f"- **阶段说明**：{stage.description}",
        f"- **建议工具**：{', '.join(stage.tools) if stage.tools else '无'}",
    ]

    progress = f"{len(result.completed_stages)}/{len(evaluator.stages)}"
    lines.append(f"- **进度**：{progress}")

    # 待收集的用户字段（核心：前置提醒，聚焦模型注意力）
    user_fields = stage.user_required_fields()
    if user_fields:
        lines.append(f"")
        lines.append(f"**待收集字段**（请向用户确认后调用 `collect_user_fields` 提交）：")
        for f in user_fields:
            desc = f.get("description", "")
            lines.append(f"  - `{f['field']}`：{desc}")

    # 可回退的 checkpoint
    if result.available_checkpoints:
        cp_names = [c["name"] for c in result.available_checkpoints]
        lines.append(f"")
        lines.append(f"- **可回退节点**：{', '.join(cp_names)}")

    return "\n".join(lines)


# ── FlowCallbacks ─────────────────────────────────────────────────────────────


class FlowCallbacks:
    """Flow 框架的三个生命周期 Hook，注入到 RunnerCallbacks。

    使用:
        fc = FlowCallbacks(sessions_dir=sessions_dir)
        RunnerCallbacks(
            before_model=[fc.before_model_flow_eval],
            after_tool=[fc.after_tool_auto_commit],
            after_agent=[fc.persist_flow_context],
        )
    """

    def __init__(self, sessions_dir: Path, ttl_hours: int = 72) -> None:
        self._sessions_dir = sessions_dir
        self._ttl_hours = ttl_hours
        self._task_registry = TaskRegistry(sessions_dir)
        # 向所有已注册 evaluator 注入 task_registry（若尚未注入）
        for ev in FlowEvaluatorRegistry.values():
            if ev._task_registry is None:
                ev._task_registry = self._task_registry

    # ── before_model ──────────────────────────────────────────────────────────

    async def before_model_flow_eval(
        self,
        ctx: CallbackContext,
        *,
        turn: int,
        messages: list[dict[str, Any]],
        **_: Any,
    ) -> CallbackResult | None:
        """before_model hook: 评估流程状态，将当前阶段信息注入到 system message。

        流程：
        1. 确定活跃的 evaluator（通过 _flow_context.skill_name 或 _turn_matched_skills）
        2. 检测 pending task（仅首次，无 flow_id 时触发）
        3. 初始化 flow_id（若无活跃流程）
        4. 调用 evaluate() 获取当前阶段
        5. 将状态写入 session.state，将提示词注入 messages
        """
        state = ctx.session.state

        flow_ctx: dict[str, Any] = dict(state.get("_flow_context") or {})

        # 确定 evaluator：
        # 优先走已激活 flow 的 skill_name（短名），否则按本轮匹配的 skill id（全名）反查。
        # Registry 在注册时同时登记短名与 "{namespace}.{skill_name}" 别名，
        # 调用方无需关心前缀差异。
        evaluator: BaseFlowEvaluator | None = None
        if flow_ctx.get("skill_name"):
            evaluator = FlowEvaluatorRegistry.get(flow_ctx["skill_name"])

        if evaluator is None:
            matched_skills: set[str] = set(state.get("_turn_matched_skills") or [])
            for sid in matched_skills:
                ev = FlowEvaluatorRegistry.get(sid)
                if ev is not None:
                    evaluator = ev
                    break

        if evaluator is None:
            return None

        # ── Pending task 检测（首次，无 flow_id）────────────────────────────
        _pending_flag = f"_pending_checked_{evaluator.skill_name}"
        if not flow_ctx.get("flow_id") and not state.get(_pending_flag):
            state[_pending_flag] = True  # 标记为已检测，避免重复
            user_id = str(state.get("user:id", ""))
            if user_id and evaluator._task_registry:
                active = evaluator._task_registry.list_active(
                    user_id, ttl_hours=evaluator._ttl_hours
                )
                pending = [t for t in active if t.get("skill_name") == evaluator.skill_name]
                if pending:
                    logger.debug("Pending task detected for user %s: %s", user_id, pending[0])
                    _append_to_system_message(messages, _format_pending_task(pending[0]))
                    return None  # 等待 LLM 向用户呈现，不初始化新流程

        # ── 初始化 flow_id（首次调用，无活跃流程）───────────────────────────
        if not flow_ctx.get("flow_id"):
            flow_ctx = {"flow_id": str(uuid.uuid4()), "skill_name": evaluator.skill_name}
            state["_flow_context"] = flow_ctx
            logger.debug(
                "Flow initialized: flow_id=%s skill=%s",
                flow_ctx["flow_id"], evaluator.skill_name,
            )

        # ── 运行评估 ────────────────────────────────────────────────────────
        result = evaluator.evaluate(flow_ctx, state)

        # 将 state_delta 写入 session.state
        for key, value in result.state_delta.items():
            apply_delta(state, key, value)
        ctx.session.updated_at = datetime.now()

        # ── 注入提示词 ──────────────────────────────────────────────────────
        _append_to_system_message(messages, _format_flow_status(result, evaluator))

        logger.debug(
            "FlowEval [turn=%d] skill=%s stage=%s done=%s",
            turn,
            evaluator.skill_name,
            result.current_stage.id if result.current_stage else "__completed__",
            result.is_done,
        )
        return None

    # ── after_tool ────────────────────────────────────────────────────────────

    async def after_tool_auto_commit(
        self,
        ctx: CallbackContext,
        *,
        turn: int,
        results: list,
        **_: Any,
    ) -> CallbackResult | None:
        """after_tool hook: 自动提交只含 source='tool' 字段且数据已就绪的阶段。

        工具执行完毕后立即运行，使 session.state 中的 _flow_context 保持最新，
        下一轮 before_model_flow_eval 可直接读到已提交的阶段状态。
        """
        state = ctx.session.state
        flow_ctx_raw: dict[str, Any] | None = state.get("_flow_context")
        if not flow_ctx_raw or not flow_ctx_raw.get("flow_id"):
            return None

        skill_name = flow_ctx_raw.get("skill_name", "")
        evaluator = FlowEvaluatorRegistry.get(skill_name)
        if not evaluator:
            return None

        # 用可变副本操作（auto_commit_tool_stages 会同步修改 flow_ctx）
        flow_ctx = dict(flow_ctx_raw)
        state_delta: dict[str, Any] = {}
        evaluator.auto_commit_tool_stages(flow_ctx, state, state_delta)

        if state_delta:
            # 同步回 session.state（flow_ctx 副本中的修改已包含在 state_delta 里）
            apply_state_delta(state, state_delta)
            # 同步 _flow_context 整体（因为 flow_ctx 副本做了 in-place 修改）
            state["_flow_context"] = flow_ctx
            ctx.session.updated_at = datetime.now()
            logger.debug(
                "AutoCommit [turn=%d] skill=%s delta_keys=%s",
                turn, skill_name, list(state_delta),
            )

        return None

    # ── after_agent ───────────────────────────────────────────────────────────

    async def persist_flow_context(
        self,
        ctx: CallbackContext,
        *,
        response: AgentMessage,
    ) -> CallbackResult | None:
        """after_agent hook: 持久化 _flow_context 到 active_tasks.json。"""
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
            # _flow_context._needs_persist=True（由 rollback 设置）时强制写盘。
            needs_persist = bool(flow_ctx.get("_needs_persist"))
            if current_stage_id != "__completed__" and not needs_persist:
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
