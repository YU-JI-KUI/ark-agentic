"""BaseFlowEvaluator — 流程评估器基类 + 相关数据结构。

业务层继承 BaseFlowEvaluator，仅需实现:
  - skill_name: str (property) — 关联的 SKILL 目录名
  - stages: list[StageDefinition] (property) — 阶段定义列表

框架层自动提供:
  - 通用阶段遍历 + Pydantic 校验
  - 跨会话可恢复状态序列化

评估器由框架通过 Hook 自动驱动:
  - before_model hook: 调用 evaluate() 注入当前阶段状态到系统提示
  - evaluate() 内部统一完成字段抽取、校验、自动提交，不再需要单独的 auto_commit 路径
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Literal

from pydantic import BaseModel, ValidationError

from .task_registry import TaskRegistry
import logging

logger = logging.getLogger(__name__)


# ── 字段定义（统一抽取策略）──────────────────────────────────────────────────


@dataclass
class FieldDefinition:
    """阶段字段定义 — 统一声明抽取策略。

    有 state_key → evaluator 自动从 session.state 抽取
    无 state_key → 需用户通过 collect_user_fields 提供（写入暂存区 _user_input_{stage_id}）
    两者都可以，evaluator 统一评估

    提取逻辑（仅 state_key 有效时，优先级：transform > path > 直接取值）：
      transform: 若提供，调用 transform(state_value) 得到字段值（适合复杂提取）
      path:      若提供，按点路径遍历 state_value（如 "identity.verified"）
      否则：     直接使用 state_value 本身
    """

    description: str = ""              # 字段说明，注入评估 message 供 LLM 参考
    state_key: str | None = None       # 自动抽取源（state 中的 key）
    path: str | None = None            # 点路径（在 state_value 内遍历）
    transform: Callable[[Any], Any] | None = field(default=None, repr=False)  # 自定义提取函数
    # 向后兼容：接受旧 FieldSource 的 source= 参数但忽略
    source: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.source is not None:
            import warnings
            warnings.warn(
                "FieldDefinition.source is deprecated and ignored; use state_key to declare auto-extraction instead",
                DeprecationWarning,
                stacklevel=2,
            )


# 向后兼容别名
FieldSource = FieldDefinition


# ── 字段评估状态 ─────────────────────────────────────────────────────────────


@dataclass
class FieldStatus:
    """单字段评估状态"""
    status: Literal["collected", "missing", "error"]
    value: Any = None           # collected 时有值
    description: str = ""       # missing 时的提示
    error: str = ""             # error 时的错误信息


@dataclass
class StageEvaluation:
    """单阶段评估结果"""
    id: str
    name: str
    status: Literal["completed", "in_progress", "pending"]
    fields: dict[str, FieldStatus] | None = None  # in_progress 时有值


# ── 阶段定义 ─────────────────────────────────────────────────────────────────


@dataclass
class StageDefinition:
    """阶段定义。

    required 语义:
      True（默认）: 必须阶段，无数据时阻塞后续阶段，视为当前阶段。
      False: 可跳过阶段，无数据时自动跳过，不阻塞后续推进。

    fields 语义:
      声明每个 output_schema 字段的抽取策略。
      有 state_key：evaluator 自动从 session.state 提取。
      无 state_key：LLM 需从用户对话中收集，通过 collect_user_fields 写入暂存区。
      未声明 fields 时，collect_user_fields 直接使用提供的 fields。

    reference_file: references/ 目录下的文件名（如 "identity_verify.md"）。
      Dynamic 注入模式以此为准，与 stage.id 解耦。

    checkpoint=True: 该阶段完成后触发 persist_flow_context 写盘，保留跨会话恢复点。

    delta_state_keys: 额外需要快照到 stage_delta 的 session.state 键。
      这些键不参与 fields 校验，仅用于 resume 时还原工具输出到 session.state。
    """

    id: str
    name: str
    description: str
    required: bool = True
    output_schema: type[BaseModel] | None = None
    reference_file: str | None = None
    tools: list[str] = field(default_factory=list)
    fields: dict[str, FieldDefinition] = field(default_factory=dict)
    checkpoint: bool = False
    delta_state_keys: list[str] = field(default_factory=list)

    # 向后兼容：field_sources 作为 fields 的别名
    @property
    def field_sources(self) -> dict[str, FieldDefinition]:
        return self.fields

    @field_sources.setter
    def field_sources(self, value: dict[str, FieldDefinition]) -> None:
        self.fields = value

    def user_required_fields(self) -> list[dict[str, str]]:
        """返回没有 state_key 的字段列表（需要用户提供），供 before_model hook 注入提示词。"""
        return [
            {"field": name, "description": fd.description or ""}
            for name, fd in self.fields.items()
            if not fd.state_key
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
    """完整评估结果"""

    flow_id: str
    skill_name: str
    is_done: bool
    is_blocked: bool = False               # True 时阻断 model 调用
    block_message: str = ""                # 阻断时的固定话术
    current_stage: StageDefinition | None = None
    stage_evaluations: list[StageEvaluation] = field(default_factory=list)
    state_delta: dict[str, Any] = field(default_factory=dict)
    available_checkpoints: list[dict[str, Any]] = field(default_factory=list)

    # 向后兼容：completed_stages 从 stage_evaluations 派生
    @property
    def completed_stages(self) -> list[dict[str, Any]]:
        """向后兼容属性：从 stage_evaluations 派生旧格式 completed_stages。"""
        result: list[dict[str, Any]] = []
        for ev in self.stage_evaluations:
            entry: dict[str, Any] = {"id": ev.id, "name": ev.name}
            if ev.status == "completed":
                entry["status"] = "completed"
            elif ev.status == "in_progress":
                entry["status"] = "incomplete"
                errors: list[str] = []
                if ev.fields:
                    for fs in ev.fields.values():
                        if fs.status == "error" and fs.error:
                            errors.append(fs.error)
                entry["errors"] = errors
            elif ev.status == "pending":
                entry["status"] = "skipped"
            result.append(entry)
        return result


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

    由 FlowCallbacks 中的 Hook 自动驱动：
      - before_model_flow_eval: 调用 evaluate() 统一评估当前阶段并注入提示词
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
    def _extract_field(state_value: Any, fd: FieldDefinition) -> Any:
        """按 FieldDefinition 声明从 session.state 值中提取字段值。"""
        if fd.transform is not None:
            return fd.transform(state_value)
        if fd.path:
            value = state_value
            for part in fd.path.split("."):
                value = value.get(part) if isinstance(value, dict) else None
            return value
        return state_value

    def evaluate(
        self,
        flow_ctx: dict[str, Any],
        state: dict[str, Any],
    ) -> FlowEvalResult:
        """统一评估：抽取所有字段 → 自动推进 → 返回结构化结果。

        in-place 修改 flow_ctx（通过 _commit_stage），调用方负责同步回 session.state。
        """
        evaluations: list[StageEvaluation] = []
        state_delta: dict[str, Any] = {}

        for stage in self.stages:
            # 已提交的阶段
            if flow_ctx.get(f"stage_{stage.id}"):
                evaluations.append(StageEvaluation(id=stage.id, name=stage.name, status="completed"))
                continue

            # 可跳过的非必须阶段
            if not stage.required and not stage.fields:
                evaluations.append(StageEvaluation(id=stage.id, name=stage.name, status="completed"))
                continue

            # 抽取所有字段
            fields_status = self._extract_all_fields(stage, state, flow_ctx)
            all_collected = all(f.status == "collected" for f in fields_status.values())
            collected = {k: v.value for k, v in fields_status.items()}

            # 仅在字段齐套后做 Pydantic 校验（类型/约束）；缺失时由 fields_status 表达
            valid: bool = True
            errors: list[str] = []
            if all_collected:
                validate_data = {name: fs.value for name, fs in fields_status.items()}
                valid, errors = stage.validate_output(validate_data)

            if all_collected and valid:
                self._commit_stage(stage, collected, flow_ctx, state, state_delta)
                evaluations.append(StageEvaluation(id=stage.id, name=stage.name, status="completed"))
                logger.info(
                    "[FlowEval] skill=%s flow_id=%s → auto-committed stage=%s (%s)",
                    self.skill_name, flow_ctx.get("flow_id", "?")[:8], stage.id, stage.name,
                )
                continue

            # 非必须阶段：有缺失或校验失败 → 跳过
            if not stage.required:
                evaluations.append(StageEvaluation(id=stage.id, name=stage.name, status="completed"))
                continue

            if not valid:
                for name, err_fs in self._mark_validation_errors(fields_status, errors).items():
                    fields_status[name] = err_fs

            evaluations.append(StageEvaluation(
                id=stage.id, name=stage.name, status="in_progress", fields=fields_status
            ))
            self._append_remaining_pending(evaluations)

            state_delta["_flow_stage"] = stage.id
            if not valid:
                logger.warning(
                    "[FlowEval] skill=%s flow_id=%s → stage=%s blocked (validation failed): %s",
                    self.skill_name, flow_ctx.get("flow_id", "?")[:8], stage.id, errors,
                )
                return FlowEvalResult(
                    flow_id=flow_ctx.get("flow_id", ""),
                    skill_name=self.skill_name,
                    is_done=False,
                    is_blocked=True,
                    block_message=f"{stage.name}信息验证失败：{errors[0] if errors else '字段有误'}",
                    current_stage=stage,
                    stage_evaluations=evaluations,
                    state_delta=state_delta,
                    available_checkpoints=list(flow_ctx.get("checkpoints") or []),
                )
            logger.info(
                "[FlowEval] skill=%s flow_id=%s → stage=%s (%s) progress=%d/%d",
                self.skill_name, flow_ctx.get("flow_id", "?")[:8],
                stage.id, stage.name,
                len([e for e in evaluations if e.status == "completed"]),
                len(self.stages),
            )
            return FlowEvalResult(
                flow_id=flow_ctx.get("flow_id", ""),
                skill_name=self.skill_name,
                is_done=False,
                is_blocked=False,
                current_stage=stage,
                stage_evaluations=evaluations,
                state_delta=state_delta,
                available_checkpoints=list(flow_ctx.get("checkpoints") or []),
            )

        # 全部完成
        state_delta["_flow_stage"] = "__completed__"
        logger.info(
            "[FlowEval] skill=%s flow_id=%s → completed (%d stages)",
            self.skill_name, flow_ctx.get("flow_id", "?")[:8], len(self.stages),
        )
        return FlowEvalResult(
            flow_id=flow_ctx.get("flow_id", ""),
            skill_name=self.skill_name,
            is_done=True,
            stage_evaluations=evaluations,
            state_delta=state_delta,
            available_checkpoints=list(flow_ctx.get("checkpoints") or []),
        )

    # ── 内部辅助 ──────────────────────────────────────────────────────────────

    def _extract_all_fields(
        self, stage: StageDefinition, state: dict[str, Any], flow_ctx: dict[str, Any]
    ) -> dict[str, FieldStatus]:
        """统一从 state + 用户输入暂存区抽取所有字段。

        FieldStatus.error 中包含字段丢失/提取失败的具体原因，供调用方诊断用。
        如果 path 指向的嵌套键不存在，会追踪路径断裂的确切位置和可用键列表。
        """
        result: dict[str, FieldStatus] = {}
        user_inputs: dict[str, Any] = flow_ctx.get(f"_user_input_{stage.id}", {}) or {}

        for name, fd in stage.fields.items():
            value = None
            reason: str | None = None

            # 优先：用户已提交的值（通过 collect_user_fields 写入暂存区）
            if name in user_inputs:
                value = user_inputs[name]
                reason = f"用户已输入: {value!r}"
            # 其次：从 state 自动抽取（有 state_key 声明时）
            elif fd.state_key:
                state_value = state.get(fd.state_key)
                if state_value is not None:
                    try:
                        value = self._extract_field(state_value, fd)
                    except Exception as e:
                        reason = f"提取异常: {type(e).__name__}: {e}"
                        value = None
                    if value is None and fd.path:
                        # 追踪路径断裂位置，产出诊断信息
                        current: Any = state_value
                        parts = fd.path.split(".")
                        for i, part in enumerate(parts):
                            if isinstance(current, dict):
                                if part in current:
                                    current = current[part]
                                else:
                                    keys_str = ", ".join(sorted(current.keys()))
                                    reason = (
                                        f"路径断裂: state_key={fd.state_key!r} 在路径第{i+1}级 "
                                        f"'{part}'处不匹配；"
                                        f"该级可用键: [{keys_str}]"
                                    )
                                    break
                            else:
                                reason = (
                                    f"路径断裂: 第{i+1}级 '{part}'处 "
                                    f"值为 {type(current).__name__}，无法导航"
                                )
                                break
                        if reason is None:
                            reason = (
                                f"路径 {fd.path!r} 在 state[{fd.state_key!r}] "
                                f"中指向的值最终为 None"
                            )
                    elif value is not None:
                        reason = f"自 state[{fd.state_key!r}] 通过 {fd.path or '直接取值'} 提取成功"
                else:
                    reason = f"state_key={fd.state_key!r} 不存在于 session.state 中"
            else:
                reason = "无 state_key，需用户对话提供"

            if value is not None:
                result[name] = FieldStatus(status="collected", value=value)
            else:
                result[name] = FieldStatus(
                    status="missing",
                    description=fd.description,
                    error=reason or "未知原因",
                )

        return result

    def _commit_stage(
        self,
        stage: StageDefinition,
        collected: dict[str, Any],
        flow_ctx: dict[str, Any],
        state: dict[str, Any],
        state_delta: dict[str, Any],
    ) -> None:
        """统一的阶段提交逻辑（唯一提交路径）。"""
        flow_ctx[f"stage_{stage.id}"] = collected
        state_delta[f"_flow_context.stage_{stage.id}"] = collected

        # 清理用户输入暂存区
        if flow_ctx.get(f"_user_input_{stage.id}"):
            flow_ctx.pop(f"_user_input_{stage.id}", None)
            state_delta[f"_flow_context._user_input_{stage.id}"] = None

        # checkpoint 处理
        if stage.checkpoint:
            existing: list[dict[str, Any]] = list(flow_ctx.get("checkpoints") or [])
            existing = [c for c in existing if c.get("stage_id") != stage.id]
            existing.append({"stage_id": stage.id, "name": stage.name, "description": stage.description})
            flow_ctx["checkpoints"] = existing
            state_delta["_flow_context.checkpoints"] = existing

        # 快照 delta（供 resume 还原）
        stage_delta: dict[str, Any] = {}
        for fd in stage.fields.values():
            if fd.state_key and fd.state_key not in stage_delta:
                raw = state.get(fd.state_key)
                if raw is not None:
                    stage_delta[fd.state_key] = raw
        for key in stage.delta_state_keys:
            if key not in stage_delta:
                raw = state.get(key)
                if raw is not None:
                    stage_delta[key] = raw
        if stage_delta:
            flow_ctx[f"stage_{stage.id}_delta"] = stage_delta
            state_delta[f"_flow_context.stage_{stage.id}_delta"] = stage_delta

    def _append_remaining_pending(self, evaluations: list[StageEvaluation]) -> None:
        """将尚未评估的阶段标记为 pending。"""
        evaluated_ids = {e.id for e in evaluations}
        for s in self.stages:
            if s.id not in evaluated_ids:
                evaluations.append(StageEvaluation(id=s.id, name=s.name, status="pending"))

    @staticmethod
    def _mark_validation_errors(
        fields_status: dict[str, FieldStatus], errors: list[str]
    ) -> dict[str, FieldStatus]:
        """将 Pydantic 校验错误映射到对应字段的 FieldStatus。

        errors 格式由 validate_output 生成:
          "('field_name',): Field required"                 ← 单字段
          "('nested', 'field'): value_error.missing"         ← 嵌套字段

        解析策略: 提取 loc tuple 中的第一级字段名作为 key。
        """
        import ast

        result = dict(fields_status)
        for err in errors:
            # 从错误字符串开头提取 loc tuple, 如 ("field_name",) 或 ("nested", "field")
            paren_end = err.find("):")
            if paren_end == -1:
                continue
            try:
                loc = ast.literal_eval(err[: paren_end + 1])
            except Exception:
                continue
            if not isinstance(loc, tuple) or not loc:
                continue
            field_name = str(loc[0])  # 取第一级字段名
            if field_name in result:
                result[field_name] = FieldStatus(
                    status="error",
                    value=fields_status[field_name].value if field_name in fields_status else None,
                    error=err,
                )
        return result

    def get_restorable_state(self, flow_ctx: dict[str, Any]) -> dict[str, Any]:
        """序列化为可持久化格式（写入 active_tasks.json）。"""
        # 直接遍历 flow_ctx 检查 stage_{id} 是否有数据来判断完成状态
        is_done = True
        current_stage_id = "__completed__"

        for stage in self.stages:
            if not self._is_stage_complete(stage, flow_ctx):
                if stage.required:
                    is_done = False
                    current_stage_id = stage.id
                    break
                # 非必须阶段跳过

        if is_done:
            current_stage_id = "__completed__"

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
