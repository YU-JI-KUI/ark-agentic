"""BaseFlowEvaluator — 流程评估器基类 + 相关数据结构。

业务层继承 BaseFlowEvaluator，仅需实现:
  - skill_name: str (property) — 关联的 SKILL 目录名
  - stages: list[StageDefinition] (property) — 阶段定义列表

框架层自动提供:
  - 通用阶段遍历 + Pydantic 校验
  - 跨会话可恢复状态序列化

评估器不再是 LLM 可调用的工具，而是由框架通过 Hook 自动驱动:
  - before_model hook: 调用 evaluate() 注入当前阶段状态到系统提示
  - after_tool hook: 调用 auto_commit_tool_stages() 自动提交工具已完成的阶段
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Literal

from pydantic import BaseModel, ValidationError

from .task_registry import TaskRegistry
import logging

logger = logging.getLogger(__name__)


# ── 字段来源声明 ──────────────────────────────────────────────────────────────


@dataclass
class FieldSource:
    """阶段 schema 字段的数据来源声明。

    source="tool": 框架从 session.state[state_key] 自动提取，LLM 无需传值。
    source="user": LLM 必须通过 collect_user_fields(fields=...) 明确提供。
                   description 字段建议填写，before_model hook 会将其注入提示词。

    提取逻辑（仅 source="tool" 时有效，优先级：transform > path > 直接取值）：
      transform: 若提供，调用 transform(state_value) 得到字段值（适合复杂提取）
      path:      若提供，按点路径遍历 state_value（如 "identity.verified"）
      否则：     直接使用 state_value 本身
    """

    source: Literal["tool", "user"] = "user"
    state_key: str | None = None
    path: str | None = None
    transform: Callable[[Any], Any] | None = field(default=None, repr=False)
    description: str | None = None  # 仅 source="user" 时有意义，by before_model hook 注入提示词


# ── 阶段定义 ─────────────────────────────────────────────────────────────────


@dataclass
class StageDefinition:
    """阶段定义。

    required 语义:
      True（默认）: 必须阶段，无数据时阻塞后续阶段，视为当前阶段。
      False: 可跳过阶段，无数据时 status="skipped"，不阻塞后续推进。

    field_sources 语义:
      声明每个 output_schema 字段的数据来源。
      source="tool"：after_tool hook 自动从 session.state 提取，不需要 LLM 操作。
      source="user"：LLM 需从用户对话中收集，before_model hook 会在提示词中列出这些字段及说明。
      未声明 field_sources 时，collect_user_fields 直接使用提供的 fields。

    reference_file: references/ 目录下的文件名（如 "identity_verify.md"）。
      Dynamic 注入模式以此为准，与 stage.id 解耦。

    checkpoint=True: 该阶段完成后触发 persist_flow_context 写盘，保留跨会话恢复点。

    delta_state_keys: 额外需要快照到 stage_delta 的 session.state 键。
      这些键不参与 field_sources 校验，仅用于 resume 时还原工具输出到 session.state。
    """

    id: str
    name: str
    description: str
    required: bool = True
    output_schema: type[BaseModel] | None = None
    reference_file: str | None = None
    tools: list[str] = field(default_factory=list)
    field_sources: dict[str, FieldSource] = field(default_factory=dict)
    checkpoint: bool = False
    delta_state_keys: list[str] = field(default_factory=list)

    def user_required_fields(self) -> list[dict[str, str]]:
        """返回 source="user" 的字段列表，供 before_model hook 注入提示词。"""
        return [
            {"field": name, "description": fs.description or ""}
            for name, fs in self.field_sources.items()
            if fs.source == "user"
        ]

    def validate_output(self, data: dict[str, Any]) -> tuple[bool, list[str]]:
        if not self.output_schema:
            return True, []
        try:
            self.output_schema(**data)
            return True, []
        except ValidationError as e:
            return False, [f"{err['loc']}: {err['msg']}" for err in e.errors()]


# ── 评估结果 ─────────────────────────────────────────────────────────────────


@dataclass
class FlowEvalResult:
    """evaluate() 的返回值，供 before_model hook 消费。"""

    is_done: bool
    current_stage: StageDefinition | None
    completed_stages: list[dict[str, Any]]
    state_delta: dict[str, Any]              # 需写入 session.state 的变更（点路径）
    available_checkpoints: list[dict[str, Any]]


# ── 全局注册表 ───────────────────────────────────────────────────────────────


class FlowEvaluatorRegistry:
    """全局单例注册表，维护 skill 标识 → evaluator 实例映射。

    业务层在 Agent 初始化时 register()；
    框架层的 before_model hook / persist_flow_context / rollback 通过 get()/values() 反查，
    无需硬编码 import。

    标识策略：始终以 evaluator.skill_name（短名）作为主键；
    若注册时提供 namespace（如 "insurance"），同时登记 "{namespace}.{skill_name}"
    作为别名，使得按 SkillEntry.id（带 agent 前缀的全名）也能命中同一实例。
    """

    _registry: dict[str, "BaseFlowEvaluator"] = {}

    @classmethod
    def register(
        cls,
        evaluator: "BaseFlowEvaluator",
        *,
        namespace: str | None = None,
    ) -> None:
        cls._registry[evaluator.skill_name] = evaluator
        if namespace:
            cls._registry[f"{namespace}.{evaluator.skill_name}"] = evaluator

    @classmethod
    def get(cls, skill_name: str) -> "BaseFlowEvaluator | None":
        return cls._registry.get(skill_name)

    @classmethod
    def all(cls) -> dict[str, "BaseFlowEvaluator"]:
        return dict(cls._registry)

    @classmethod
    def values(cls) -> list["BaseFlowEvaluator"]:
        """返回所有注册的 evaluator 实例列表（去重，因同一实例可能登记多个别名）。"""
        seen: set[int] = set()
        result: list[BaseFlowEvaluator] = []
        for ev in cls._registry.values():
            if id(ev) not in seen:
                seen.add(id(ev))
                result.append(ev)
        return result


# ── BaseFlowEvaluator 抽象基类 ────────────────────────────────────────────────


class BaseFlowEvaluator(ABC):
    """流程评估器基类（框架层）。

    每个业务流程继承此类，仅需定义 skill_name 和 stages。
    基类提供通用的阶段遍历、Pydantic 校验、状态恢复等能力。

    不再是 LLM 可调用的工具。由 FlowCallbacks 中的 Hook 自动驱动：
      - before_model_flow_eval: 调用 evaluate() 获取当前阶段，注入到系统提示
      - after_tool_auto_commit: 调用 auto_commit_tool_stages() 自动提交工具阶段
    """

    def __init__(self) -> None:
        self._task_registry: TaskRegistry | None = None
        self._ttl_hours: int = 72

    @property
    @abstractmethod
    def skill_name(self) -> str:
        """关联的 SKILL 目录名。"""
        ...

    @property
    @abstractmethod
    def stages(self) -> list[StageDefinition]:
        """子类必须定义阶段列表（有序）。"""
        ...

    @property
    def task_name_template(self) -> str:
        """任务名模板（供 persist_flow_context 渲染进 active_tasks.json）。

        可用变量来自已完成阶段 data（展平）+ flow_ctx 顶层键；
        未就绪的变量渲染为字面量 "{待定}"。
        默认实现退化为 skill_name，业务层按需覆写。
        """
        return self.skill_name

    def render_task_name(self, flow_ctx: dict[str, Any]) -> str:
        """按 task_name_template 渲染任务名。

        命名空间优先级：完成阶段 data 展平 < flow_ctx 顶层键（同名时后者胜出）。
        缺失变量返回字面量 "{待定}" 而非抛异常，避免模板错误打断流程持久化。
        """
        ns: dict[str, Any] = {}
        for key, value in flow_ctx.items():
            if (
                key.startswith("stage_")
                and not key.endswith("_delta")
                and isinstance(value, dict)
            ):
                ns.update(value)
        for key, value in flow_ctx.items():
            if not key.startswith("stage_"):
                ns[key] = value

        # _Missing 需同时支持普通 {x} 和带格式规约的 {x:.0f} 两种占位形式。
        # 对任意 format_spec 都返回字面量 "{待定}"，避免模板变量类型（float/int/str）
        # 差异导致 format_map 抛 ValueError。
        class _Missing:
            def __format__(self, spec: str) -> str:
                return "{待定}"

            def __str__(self) -> str:
                return "{待定}"

        class _SafeDict(dict):
            def __missing__(self, key: str) -> "_Missing":
                return _Missing()

        try:
            return self.task_name_template.format_map(_SafeDict(ns))
        except Exception:
            logger.warning(
                "render_task_name failed for skill=%s template=%r",
                self.skill_name, self.task_name_template,
            )
            return self.skill_name

    @staticmethod
    def _extract_field(state_value: Any, fs: FieldSource) -> Any:
        """按 FieldSource 声明从 session.state 值中提取字段值。"""
        if fs.transform is not None:
            return fs.transform(state_value)
        if fs.path:
            value = state_value
            for part in fs.path.split("."):
                value = value.get(part) if isinstance(value, dict) else None
            return value
        return state_value

    def evaluate(
        self,
        flow_ctx: dict[str, Any],
        state: dict[str, Any],
    ) -> FlowEvalResult:
        """运行一次完整的流程评估（供 before_model hook 调用）。

        读取当前 flow_ctx（由 after_tool_auto_commit 维护），
        确定当前阶段并构造需写入 session.state 的 state_delta。
        不再执行 auto_commit（由 after_tool hook 专门负责）。
        """
        completed, is_done = self._evaluate_stages(flow_ctx)

        state_delta: dict[str, Any] = {}

        if is_done:
            state_delta["_flow_stage"] = "__completed__"
            logger.info(
                "[FlowEval] skill=%s flow_id=%s → completed (%d/%d stages done)",
                self.skill_name,
                flow_ctx.get("flow_id", "?")[:8],
                len(completed),
                len(self.stages),
            )
            return FlowEvalResult(
                is_done=True,
                current_stage=None,
                completed_stages=completed,
                state_delta=state_delta,
                available_checkpoints=list(flow_ctx.get("checkpoints") or []),
            )

        # 确定当前阶段
        if completed and completed[-1]["status"] == "incomplete":
            current_stage = self.stages[len(completed) - 1]
        else:
            current_stage = self.stages[len(completed)]

        state_delta["_flow_stage"] = current_stage.id

        # 日志：当前阶段、进度、已完成阶段列表
        completed_ids = [s["id"] for s in completed]
        logger.info(
            "[FlowEval] skill=%s flow_id=%s → stage=%s (%s) progress=%d/%d completed=%s",
            self.skill_name,
            flow_ctx.get("flow_id", "?")[:8],
            current_stage.id,
            current_stage.name,
            len(completed),
            len(self.stages),
            completed_ids,
        )

        return FlowEvalResult(
            is_done=False,
            current_stage=current_stage,
            completed_stages=completed,
            state_delta=state_delta,
            available_checkpoints=list(flow_ctx.get("checkpoints") or []),
        )

    def auto_commit_tool_stages(
        self,
        flow_ctx: dict[str, Any],
        state: dict[str, Any],
        state_delta: dict[str, Any],
    ) -> None:
        """自动提交只含 source='tool' 字段且数据已就绪的阶段（供 after_tool hook 调用）。

        当阶段的所有字段均来自工具输出（source='tool'）且对应 state_key
        已存在于 session.state 时，自动提取、校验并写入 flow_ctx 和 state_delta。

        按阶段顺序处理：遇到无法自动提交的阶段（含 user 字段、数据缺失、校验失败）即停止，
        不会跳过中间阶段去提交后续阶段。
        """
        stop_reason = ""
        for stage in self.stages:
            if flow_ctx.get(f"stage_{stage.id}"):
                continue  # 已提交，跳过

            if not stage.field_sources:
                stop_reason = f"stage '{stage.id}' has no field_sources"
                break  # 无 field_sources 声明，需显式提交，停止

            if any(fs.source == "user" for fs in stage.field_sources.values()):
                stop_reason = f"stage '{stage.id}' has user-source fields"
                break  # 含用户字段，需 LLM 通过 collect_user_fields 收集，停止

            # 全为 source="tool"，尝试提取数据
            collected: dict[str, Any] = {}
            all_available = True
            for field_name, fs in stage.field_sources.items():
                if not fs.state_key:
                    all_available = False
                    break
                state_value = state.get(fs.state_key)
                if state_value is None:
                    all_available = False
                    break
                collected[field_name] = self._extract_field(state_value, fs)

            if not all_available:
                missing = [fs.state_key for fs in stage.field_sources.values()
                           if fs.source == "tool" and state.get(fs.state_key) is None]
                stop_reason = f"stage '{stage.id}' missing state keys: {missing}"
                break  # 数据未就绪，停止

            valid, errors = stage.validate_output(collected)
            if not valid:
                stop_reason = f"stage '{stage.id}' validation failed: {errors}"
                break  # 校验失败，停止

            # 写入 flow_ctx（内存）和 state_delta（后续持久化）
            flow_ctx[f"stage_{stage.id}"] = collected
            state_delta[f"_flow_context.stage_{stage.id}"] = collected

            # checkpoint 阶段：追加到 checkpoints 列表
            if stage.checkpoint:
                existing: list[dict[str, Any]] = list(flow_ctx.get("checkpoints") or [])
                existing = [c for c in existing if c.get("stage_id") != stage.id]
                existing.append({
                    "stage_id": stage.id,
                    "name": stage.name,
                    "description": stage.description,
                })
                flow_ctx["checkpoints"] = existing
                state_delta["_flow_context.checkpoints"] = existing

            # 快照 delta（原始 state 值 + delta_state_keys），供 resume 时还原
            stage_delta: dict[str, Any] = {}
            for fs in stage.field_sources.values():
                if fs.source == "tool" and fs.state_key and fs.state_key not in stage_delta:
                    raw = state.get(fs.state_key)
                    if raw is not None:
                        stage_delta[fs.state_key] = raw
            for key in stage.delta_state_keys:
                if key not in stage_delta:
                    raw = state.get(key)
                    if raw is not None:
                        stage_delta[key] = raw
            if stage_delta:
                flow_ctx[f"stage_{stage.id}_delta"] = stage_delta
                state_delta[f"_flow_context.stage_{stage.id}_delta"] = stage_delta

            logger.info(
                "[AutoCommit] skill=%s stage=%s (%s) fields=%s checkpoint=%s",
                self.skill_name, stage.id, stage.name, list(collected), stage.checkpoint,
            )

        if stop_reason:
            logger.debug("[AutoCommit] skill=%s stopped: %s", self.skill_name, stop_reason)

    # ── 内部辅助 ──────────────────────────────────────────────────────────────

    def _evaluate_stages(
        self, flow_ctx: dict[str, Any]
    ) -> tuple[list[dict[str, Any]], bool]:
        """遍历阶段，返回 (已处理阶段列表, 是否全部完成)。

        返回的列表中每项 status: "completed" | "skipped" | "incomplete"。
        遇到当前阶段（无数据或校验失败）时停止遍历。
        """
        completed: list[dict[str, Any]] = []
        for stage in self.stages:
            stage_data = flow_ctx.get(f"stage_{stage.id}", {})
            if not stage_data:
                if not stage.required:
                    completed.append({"id": stage.id, "name": stage.name, "status": "skipped"})
                    continue
                break  # 必须阶段无数据 → 当前阶段

            valid, errors = stage.validate_output(stage_data)
            if valid:
                completed.append({"id": stage.id, "name": stage.name, "status": "completed"})
            else:
                completed.append({
                    "id": stage.id, "name": stage.name,
                    "status": "incomplete", "errors": errors,
                })
                break

        is_done = (
            len(completed) == len(self.stages)
            and all(s["status"] in ("completed", "skipped") for s in completed)
        )
        return completed, is_done

    def get_restorable_state(self, flow_ctx: dict[str, Any]) -> dict[str, Any]:
        """序列化为可持久化格式（写入 active_tasks.json）。"""
        completed, is_done = self._evaluate_stages(flow_ctx)
        if is_done:
            current_stage_id = "__completed__"
        elif completed and completed[-1]["status"] == "incomplete":
            current_stage_id = completed[-1]["id"]
        else:
            current_stage_id = (
                self.stages[len(completed)].id
                if len(completed) < len(self.stages)
                else "__completed__"
            )

        return {
            "flow_id": flow_ctx.get("flow_id"),
            "skill_name": self.skill_name,
            "current_stage": current_stage_id,
            "stages": {
                stage.id: {
                    "status": "completed" if self._is_stage_complete(stage, flow_ctx) else "pending",
                    "data": flow_ctx.get(f"stage_{stage.id}", {}),
                    "delta": flow_ctx.get(f"stage_{stage.id}_delta", {}),
                }
                for stage in self.stages
            },
        }

    def _is_stage_complete(self, stage: StageDefinition, flow_ctx: dict[str, Any]) -> bool:
        stage_data = flow_ctx.get(f"stage_{stage.id}", {})
        if not stage_data:
            return not stage.required
        valid, _ = stage.validate_output(stage_data)
        return valid
