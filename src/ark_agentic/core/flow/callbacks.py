"""Flow 框架级回调实现。

三个 Hook 构成完整的 Flow 生命周期管理：

  before_model_flow_eval — before_model hook:
    每轮 LLM 调用前自动运行评估器，将当前阶段状态注入到系统提示词中。
    evaluate() 内部统一完成字段抽取、校验、自动提交。
    处理 pending task 检测（替代原 evaluator.execute() 中的逻辑）。

  before_tool_stage_guard — before_tool hook:
    在工具执行前检查 LLM 是否「越级调用下游 stage 的工具」。命中时合成
    ToolLoopAction.STOP 的 tool_results，复用 _tool_phase 的 STOP 收尾路径，
    向用户输出固定话术。

  persist_flow_context — after_agent hook:
    持久化 _flow_context 到 active_tasks.json。

使用方式:
    from ark_agentic.core.flow.callbacks import FlowCallbacks
    from ark_agentic.core.runtime.callbacks import RunnerCallbacks

    fc = FlowCallbacks(sessions_dir=sessions_dir)
    callbacks = RunnerCallbacks(
        before_model=[fc.before_model_flow_eval],
        before_tool=[fc.before_tool_stage_guard],
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

from ..runtime.callbacks import CallbackContext, CallbackResult, HookAction
from ..skills.base import _escape_xml
from ..state_utils import apply_delta
from ..types import (
    AgentMessage,
    AgentToolResult,
    ToolCall,
    ToolLoopAction,
    ToolResultType,
)
from .base_evaluator import BaseFlowEvaluator, FlowEvalResult, FlowEvaluatorRegistry
from .task_registry import TaskRegistry

logger = logging.getLogger(__name__)


# ── 消息注入辅助 ──────────────────────────────────────────────────────────────


def _append_to_system_message(messages: list[dict[str, Any]], content: str) -> None:
    """将 content 追加到第一个 system message 末尾。若不存在则插入。"""
    for i, msg in enumerate(messages):
        if msg.get("role") == "system":
            messages[i] = {**msg, "content": msg["content"] + f"\n\n{content}"}
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


# 与阶段 reference 解耦：凡注入 flow_evaluation 且流程未结束时附于 JSON 之前。
_FLOW_EVALUATION_PROTOCOL = """\
### 流程评估约定（框架通用）

以下约定适用于**当前** `flow_evaluation` 中的 JSON。

- **`current_stage.outstanding_fields`（见下方 JSON）**
  - `missing`：向用户说明缺什么、为何需要；若 `hint` 要求则在与用户确认后调用 `collect_user_fields`。在 outstanding **未清空**前，业务工具**仅**使用当前 JSON 中 `suggested_tools`（及技能允许的通用工具如 `resume_task` / `rollback_flow_stage` 等）；**勿**调用仅属于后续阶段的工具。
  - `error`：按 `error` / `hint` 修正或向用户澄清，可重试本阶段工具；勿宣称已进入后续阶段或替用户推进下一阶段。

- **以本块为准**：若工具 JSON 看似满足某条件，但此处仍为 `incomplete` / `invalid`，说明评估状态尚未对齐，须继续按 outstanding 处理。

- **阶段守卫**：若同轮出现「当前流程阶段「…」尚未完成，请先按提示完成本阶段后再继续」——表示越级工具已被拦截。须**撤回**对后续阶段的表述，只处理 outstanding 与本阶段工具；
"""


def _build_evaluation_message(result: FlowEvalResult) -> str:
    """与主系统提示一致：``<flow_evaluation>`` 包裹，内层为简短说明 + fenced JSON。

    JSON 负载：``process_name``、``flow_status`` / ``current_stage``、
    ``outstanding_fields``；无 ``state_key`` 的缺失项在 ``hint`` 中并入
    ``collect_user_fields`` 说明。
    """
    current_stage_eval = next(
        (e for e in result.stage_evaluations if e.status == "in_progress"), None
    )

    eval_json: dict[str, Any] = {
        "process_name": "当前流程执行状态评估",
    }

    if result.is_done:
        eval_json["flow_status"] = "completed"
    elif result.current_stage and current_stage_eval:
        defs = result.current_stage.fields
        outstanding: dict[str, Any] = {}
        has_field_error = False
        if current_stage_eval.fields:
            for name, fs in current_stage_eval.fields.items():
                if fs.status not in ("missing", "error"):
                    continue
                entry: dict[str, Any] = {"status": fs.status}
                if fs.status == "missing":
                    hint_parts: list[str] = []
                    if fs.description:
                        hint_parts.append(fs.description)
                    # 工具侧缺失时 error 为抽取诊断（如 state_key 未就位），必须透出否则 JSON 只剩裸 status
                    if fs.error:
                        hint_parts.append(fs.error)
                    fd = defs.get(name)
                    if fd is not None and not fd.state_key:
                        hint_parts.append(
                            "请向用户确认后调用 `collect_user_fields` 提交该字段。"
                        )
                    if hint_parts:
                        entry["hint"] = " ".join(hint_parts)
                if fs.status == "error" and fs.error:
                    entry["error"] = fs.error
                    has_field_error = True
                outstanding[name] = entry

        eval_json["current_stage"] = {
            "id": result.current_stage.id,
            "name": result.current_stage.name,
            "result": "invalid" if has_field_error else "incomplete",
            "suggested_tools": result.current_stage.tools,
            "outstanding_fields": outstanding,
        }

    body_json = json.dumps(eval_json, ensure_ascii=False, indent=2)
    prefix = "" if result.is_done else _FLOW_EVALUATION_PROTOCOL + "\n"
    inner = (
        f"{prefix}"
        "当前流程结构化状态：\n\n"
        f"```json\n{body_json}\n```\n"
    )
    return f"<flow_evaluation>\n{inner}</flow_evaluation>"


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
        # 合并到第一条 system 消息而非 append 新 system 消息：
        # 多数 LLM API（国产模型/内部 vLLM）只认一条 system 消息，多条会导致第二条被忽略。
        eval_msg = _build_evaluation_message(result)
        _append_to_system_message(messages, eval_msg)

        return None

    # ── before_tool ───────────────────────────────────────────────────────────

    async def before_tool_stage_guard(
        self,
        ctx: CallbackContext,
        *,
        turn: int,
        tool_calls: list[ToolCall],
        **_: Any,
    ) -> CallbackResult | None:
        """阻断越级调用：当前 stage 未完成、LLM 却调用了下游 stage 的专属工具。

        判定规则：
          1. 必须存在已激活流程（`_flow_context.skill_name` 与 `current_stage`）。
          2. `current_stage` 不为 `__completed__`。
          3. tool_call.name 命中某个 stage_idx > current_idx 的 `StageDefinition.tools`。
          4. 不在任何 stage.tools 中的工具视作通用工具（resume_task / collect_user_fields /
             rollback_flow_stage / read_skill / memory 等），一律放行。

        命中时合成 STOP tool_results：runner._tool_phase 的 STOP 收尾路径
        会拼出 assistant 回复并立刻退出 loop，等价于「踩刹车」。
        """
        flow_ctx: dict[str, Any] = ctx.session.state.get("_flow_context") or {}
        skill_name = flow_ctx.get("skill_name", "")
        current_stage_id = flow_ctx.get("current_stage")
        if not skill_name or not current_stage_id or current_stage_id == "__completed__":
            return None

        evaluator = FlowEvaluatorRegistry.get(skill_name)
        if evaluator is None:
            return None

        stage_index = {s.id: i for i, s in enumerate(evaluator.stages)}
        cur_idx = stage_index.get(current_stage_id)
        if cur_idx is None:
            return None

        future_tools: set[str] = set()
        for s in evaluator.stages[cur_idx + 1 :]:
            future_tools.update(s.tools)
        if not future_tools:
            return None

        offending = [tc for tc in tool_calls if tc.name in future_tools]
        if not offending:
            return None

        current_stage = evaluator.stages[cur_idx]
        fixed_message = (
            f"当前流程阶段「{current_stage.name}」尚未完成，"
            f"请先按提示完成本阶段后再继续。"
        )
        logger.warning(
            "[FlowGuard] skill=%s flow_id=%s stage=%s blocked future-stage tool_calls=%s",
            skill_name,
            flow_ctx.get("flow_id", "?")[:8],
            current_stage_id,
            [tc.name for tc in offending],
        )

        # 同时为本回合所有 tool_calls 合成 STOP 结果，避免越级工具实际执行。
        # 越级工具 → STOP+固定话术；其他工具 → STOP+空，统一终止本轮。
        stop_results: list[AgentToolResult] = []
        for tc in tool_calls:
            if tc.name in future_tools:
                stop_results.append(
                    AgentToolResult(
                        tool_call_id=tc.id,
                        result_type=ToolResultType.TEXT,
                        content=fixed_message,
                        loop_action=ToolLoopAction.STOP,
                    )
                )
            else:
                stop_results.append(
                    AgentToolResult(
                        tool_call_id=tc.id,
                        result_type=ToolResultType.TEXT,
                        content="",
                        loop_action=ToolLoopAction.STOP,
                    )
                )
        return CallbackResult(action=HookAction.OVERRIDE, tool_results=stop_results)

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
            from ..runtime.runner import _read_reference_file  # 复用运行器侧的 lru_cache
            ref_content = _read_reference_file(str(ref_path))
        except Exception as e:
            logger.warning("[FlowEval] failed to read reference %s: %s", ref_path, e)
            return None
        attrs = (
            f'stage_id="{_escape_xml(current_stage_id)}" '
            f'name="{_escape_xml(stage_def.name)}" '
            f'file="{_escape_xml(stage_def.reference_file)}"'
        )
        return f"<flow_reference {attrs}>\n{ref_content}\n</flow_reference>"

    # ── after_agent ───────────────────────────────────────────────────────────

    async def persist_flow_context(
        self,
        ctx: CallbackContext,
        *,
        response: AgentMessage,
        **kwargs: Any,
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
            persistable = evaluator.get_persistable_context(flow_ctx)
            current_stage_id = persistable.get("current_stage", "__completed__")

            # checkpoint 检查：只在最后完成的阶段标记了 checkpoint=True 时写盘；
            # 流程已全部完成（__completed__）时始终写盘以触发 TaskRegistry 清理。
            if current_stage_id != "__completed__":
                completed_ids = [
                    s.id for s in evaluator.stages
                    if persistable.get(f"stage_{s.id}")
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
                flow_context_snapshot=persistable,
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
