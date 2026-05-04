"""Flow 框架级回调实现。

两个 Hook 构成完整的 Flow 生命周期管理：

  before_model_flow_eval — before_model hook:
    每轮 LLM 调用前自动运行评估器，将当前阶段状态注入到系统提示词中。
    evaluate() 内部统一完成字段抽取、校验、自动提交。
    处理 pending task 检测（替代原 evaluator.execute() 中的逻辑）。
    当 is_blocked=True 时通过 CallbackResult.block_model 阻断 LLM 调用。

  persist_flow_context — after_agent hook:
    持久化 _flow_context 到 active_tasks.json。

使用方式:
    from ark_agentic.core.flow.callbacks import FlowCallbacks
    from ark_agentic.core.callbacks import RunnerCallbacks

    fc = FlowCallbacks(sessions_dir=sessions_dir)
    callbacks = RunnerCallbacks(
        before_model=[fc.before_model_flow_eval],
        after_agent=[fc.persist_flow_context],
    )
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from ..callbacks import CallbackContext, CallbackResult
from ..state_utils import apply_delta
from ..types import AgentMessage
from .base_evaluator import BaseFlowEvaluator, FlowEvalResult, FlowEvaluatorRegistry
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


def _format_ms_ts(ms: int | None) -> str:
    """把 epoch 毫秒格式化为 'YYYY-MM-DD HH:MM:SS'（本地时区）。ms 缺失/无效返回空串。"""
    if not ms:
        return ""
    try:
        return datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, OSError):
        return ""


def _format_pending_tasks_json(tasks: list[dict[str, Any]]) -> str:
    """格式化 pending task 列表为 JSON 数组形式的提示词。

    输出结构：[{task_name, flow_id, current_stage, last_runtime}]。
    - task_name 缺失时回退到 skill_name，兼容旧 active_tasks 记录。
    - last_runtime 由 updated_at（epoch ms）格式化为可读字符串。
    - 即便只有 1 条任务也用数组，降低 LLM 解析歧义。
    """
    payload = [
        {
            "task_name": t.get("task_name") or t.get("skill_name", ""),
            "flow_id": t.get("flow_id", ""),
            "current_stage": t.get("current_stage", ""),
            "last_runtime": _format_ms_ts(t.get("updated_at")),
        }
        for t in tasks
    ]
    tasks_json = json.dumps(payload, ensure_ascii=False, indent=2)
    return (
        "## 检测到未完成的流程任务\n\n"
        "以下任务仍未完成（JSON 数组，每项对应一个可恢复的流程）：\n\n"
        "```json\n"
        f"{tasks_json}\n"
        "```\n\n"
        "请先向用户列出这些任务并等待明确答复后，再调用工具：\n"
        "- 继续某项 → `resume_task(flow_id=\"<数组中对应条目的 flow_id>\", action=\"resume\")`\n"
        "- 放弃某项 → `resume_task(flow_id=\"<数组中对应条目的 flow_id>\", action=\"discard\")`\n\n"
        "严禁未得到用户明确答复前调用 resume_task。"
    )


def _summarize_value(value: Any, max_len: int = 200) -> Any:
    """对 collected 值做轻量摘要。"""
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    s = str(value)
    return s if len(s) <= max_len else s[:max_len] + "..."


def _build_evaluation_message(result: FlowEvalResult) -> dict[str, Any]:
    """构造评估结果独立消息，包含结构化 JSON。"""
    current_stage_eval = next(
        (e for e in result.stage_evaluations if e.status == "in_progress"), None
    )

    eval_json: dict[str, Any] = {
        "flow_id": result.flow_id,
        "skill_name": result.skill_name,
        "current_stage": None,
        "stages_overview": [
            {"id": e.id, "name": e.name, "status": e.status}
            for e in result.stage_evaluations
        ],
    }

    if result.current_stage and current_stage_eval:
        fields_dict: dict[str, Any] = {}
        if current_stage_eval.fields:
            for name, fs in current_stage_eval.fields.items():
                entry: dict[str, Any] = {"status": fs.status}
                if fs.status == "collected":
                    entry["value"] = _summarize_value(fs.value)
                if fs.status == "missing" and fs.description:
                    entry["hint"] = fs.description
                if fs.status == "error" and fs.error:
                    entry["error"] = fs.error
                fields_dict[name] = entry

        eval_json["current_stage"] = {
            "id": result.current_stage.id,
            "name": result.current_stage.name,
            "result": "blocked" if result.is_blocked else "incomplete",
            "suggested_tools": result.current_stage.tools,
            "fields": fields_dict,
        }

    content = f"## Flow Evaluation\n\n```json\n{json.dumps(eval_json, ensure_ascii=False, indent=2)}\n```"

    if current_stage_eval and current_stage_eval.fields:
        missing = [name for name, fs in current_stage_eval.fields.items() if fs.status == "missing"]
        if missing:
            content += "\n\n请向用户收集缺失字段后调用 `collect_user_fields` 提交。"

    return {"role": "system", "content": content}


# ── FlowCallbacks ─────────────────────────────────────────────────────────────


class FlowCallbacks:
    """Flow 框架的生命周期 Hook，注入到 RunnerCallbacks。

    使用:
        fc = FlowCallbacks(sessions_dir=sessions_dir)
        RunnerCallbacks(
            before_model=[fc.before_model_flow_eval],
            after_agent=[fc.persist_flow_context],
        )
    """

    def __init__(
        self,
        sessions_dir: Path,
        ttl_hours: int = 72,
        skill_loader: Any | None = None,
    ) -> None:
        self._sessions_dir = sessions_dir
        self._ttl_hours = ttl_hours
        self._task_registry = TaskRegistry(sessions_dir)
        # skill_loader 用于运行期按当前阶段定位 reference 文件（path/references/<file>）。
        # 取代 runner._enrich_skills_with_stage_reference，统一注入路径并消除"加载两次"。
        self._skill_loader = skill_loader
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
        """before_model hook: 评估流程状态，将当前阶段信息和阶段 reference 注入到 system message。

        流程：
        1. 确定活跃的 evaluator（通过 _flow_context.skill_name 或 _turn_matched_skills）
        2. 检测 pending task（每轮都检测，直到 LLM 调 resume_task 处理）
        3. 初始化 flow_id（若无活跃流程且无 pending）
        4. 调用 evaluate() 获取当前阶段
        5. 将状态写入 session.state，将状态提示和当前阶段 reference 注入 messages
        """
        state = ctx.session.state

        flow_ctx: dict[str, Any] = dict(state.get("_flow_context") or {})

        # 确定 evaluator：
        # 优先走已激活 flow 的 skill_name（短名），否则按本轮匹配的 skill id（全名）反查。
        # Registry 在注册时同时登记短名与 "{namespace}.{skill_name}" 别名，
        # 调用方无需关心前缀差异。
        evaluator: BaseFlowEvaluator | None = None
        matched_full_id: str | None = None
        if flow_ctx.get("skill_name"):
            evaluator = FlowEvaluatorRegistry.get(flow_ctx["skill_name"])

        if evaluator is None:
            matched_skills: set[str] = set(state.get("_turn_matched_skills") or [])
            for sid in matched_skills:
                ev = FlowEvaluatorRegistry.get(sid)
                if ev is not None:
                    evaluator = ev
                    matched_full_id = sid
                    break

        if evaluator is None:
            return None

        # ── Pending task 检测（每轮直检 registry，无短路 flag）──────────────
        # 旧版用 _pending_checked_<skill> flag 在第一轮置 True 后跳过后续轮检测，
        # 但若用户在后续轮才决定 resume/discard，提示词里就不再有 flow_id，LLM 无从下手。
        # 改为每轮直接读 registry：用户做决定前 JSON 提示持续可见；做完决定后
        # （discard 移除记录 / resume 写入 flow_ctx），下一轮自然不会再触发。
        if not flow_ctx.get("flow_id"):
            user_id = str(state.get("user:id", ""))
            if user_id and evaluator._task_registry:
                active = evaluator._task_registry.list_active(
                    user_id, ttl_hours=evaluator._ttl_hours
                )
                pending = [t for t in active if t.get("skill_name") == evaluator.skill_name]
                if pending:
                    logger.debug(
                        "Pending task(s) detected for user %s skill=%s count=%d",
                        user_id, evaluator.skill_name, len(pending),
                    )
                    _append_to_system_message(messages, _format_pending_tasks_json(pending))
                    return None  # 等待 LLM 向用户呈现，不初始化新流程

        # ── 初始化 flow_id（首次调用，无活跃流程，且无 pending 任务）────────
        if not flow_ctx.get("flow_id"):
            user_id = str(state.get("user:id", ""))
            # 短 flow_id 依赖 TaskRegistry 的 per-user 查重；无 user_id 时降级为纯时间前缀
            new_flow_id = (
                self._task_registry.generate_flow_id(user_id)
                if user_id
                else f"{datetime.now().strftime('%y%m%d')}-{uuid.uuid4().hex[:4]}"
            )
            flow_ctx = {"flow_id": new_flow_id, "skill_name": evaluator.skill_name}
            state["_flow_context"] = flow_ctx
            logger.debug(
                "Flow initialized: flow_id=%s skill=%s",
                flow_ctx["flow_id"], evaluator.skill_name,
            )

        # ── 运行评估 ────────────────────────────────────────────────────────
        result = evaluator.evaluate(flow_ctx, state)
        # 注入当前阶段 reference：单一注入路径，避免 loader 全量 dump + runner 二次 enrich 的双重加载
        if result.current_stage is not None:
            ref_block = self._build_stage_reference_block(
                evaluator, result.current_stage.id, matched_full_id
            )
            if ref_block:
                _append_to_system_message(messages, ref_block)

        # 将 state_delta 写入 session.state（evaluate 内部会 in-place 修改 flow_ctx）
        for key, value in result.state_delta.items():
            apply_delta(state, key, value)
        # 同步 flow_ctx 整体（evaluate 内部 in-place 修改了 flow_ctx）
        state["_flow_context"] = flow_ctx
        ctx.session.updated_at = datetime.now()

        # ── 注入提示词 ──────────────────────────────────────────────────────
        messages.append(_build_evaluation_message(result))

        if result.is_blocked:
            return CallbackResult(block_model=True, inject_response=result.block_message)

        return None

    def _build_stage_reference_block(
        self,
        evaluator: BaseFlowEvaluator,
        current_stage_id: str,
        matched_full_id: str | None,
    ) -> str | None:
        """构造当前阶段的 reference 注入文本块（找不到则返回 None，自然降级）。"""
        if current_stage_id == "__completed__" or self._skill_loader is None:
            return None
        stage_def = next(
            (s for s in evaluator.stages if s.id == current_stage_id), None
        )
        if stage_def is None or not stage_def.reference_file:
            return None

        # 优先用本轮匹配的 full skill id 反查 path；缺失则按 evaluator.skill_name 兜底
        skill_entry = None
        if matched_full_id:
            skill_entry = self._skill_loader.get_skill(matched_full_id)
        if skill_entry is None:
            for sk in self._skill_loader.list_skills():
                if sk.id.endswith(f".{evaluator.skill_name}") or sk.id == evaluator.skill_name:
                    skill_entry = sk
                    break
        if skill_entry is None:
            return None

        ref_path = Path(skill_entry.path) / "references" / stage_def.reference_file
        if not ref_path.exists():
            logger.warning("[FlowEval] reference file not found: %s", ref_path)
            return None
        try:
            from ..runner import _read_reference_file  # 复用运行器侧的 lru_cache
            ref_content = _read_reference_file(str(ref_path))
        except Exception as e:
            logger.warning("[FlowEval] failed to read reference %s: %s", ref_path, e)
            return None
        return f"### 当前阶段参考: {current_stage_id}\n\n{ref_content}"

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

            # 每次写盘都重渲染 task_name；阶段推进后，模板中原本的 {待定} 变量
            # 会被已提交的 stage data 替换为具体值（如 amount）。
            task_name = evaluator.render_task_name(flow_ctx)

            registry = TaskRegistry(base_dir=self._sessions_dir)
            registry.upsert(
                user_id=str(user_id),
                flow_id=flow_ctx["flow_id"],
                skill_name=skill_name,
                current_stage=current_stage_id,
                last_session_id=session.session_id,
                flow_context_snapshot=restorable,
                task_name=task_name,
                resume_ttl_hours=self._ttl_hours,
            )
            logger.debug(
                "Persisted flow '%s' stage='%s' task_name='%s' for user %s",
                flow_ctx["flow_id"], current_stage_id, task_name, user_id,
            )
        except Exception:
            logger.warning("Failed to persist flow context", exc_info=True)

        return None
