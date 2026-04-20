"""BaseFlowEvaluator — 流程评估器基类 + 相关数据结构。

业务层继承 BaseFlowEvaluator，仅需实现:
  - skill_name: str (property) — 关联的 SKILL 目录名，同时作为工具 name 前缀
  - stages: list[StageDefinition] (property) — 阶段定义列表

框架层自动提供:
  - 通用阶段遍历 + Pydantic 校验
  - _flow_stage state_delta 写入
  - user_required_fields 自动推导（从 field_sources 中 source="user" 的字段）
  - 跨会话可恢复状态序列化

阶段数据写入约定:
  业务完成后，LLM 调用 commit_flow_stage(stage_id=..., user_data={...}) 提交阶段数据。
  框架自动从 session.state 提取 source="tool" 字段，LLM 仅需提供 source="user" 字段。
  当阶段存在 source="user" 字段时，evaluator 响应中会列出待收集字段及说明，
  由模型自主决定何时向用户询问并提交，无需框架硬性中断 ReAct 循环。
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Literal

from pydantic import BaseModel, ValidationError

from ..tools.base import AgentTool, ToolParameter
from ..types import AgentToolResult, ToolCall, ToolResultType
from .task_registry import TaskRegistry
import logging

logger = logging.getLogger(__name__)
# ── 字段来源声明 ──────────────────────────────────────────────────────────────


@dataclass
class FieldSource:
    """阶段 schema 字段的数据来源声明，供 CommitFlowStageTool 使用。

    source="tool": 框架从 session.state[state_key] 自动提取，LLM 无需传值。
    source="user": LLM 必须通过 commit_flow_stage(user_data=...) 明确提供。
                   description 字段建议填写，evaluator 会将其暴露给模型指导收集。

    提取逻辑（仅 source="tool" 时有效，优先级：transform > path > 直接取值）：
      transform: 若提供，调用 transform(state_value) 得到字段值（适合复杂提取）
      path:      若提供，按点路径遍历 state_value（如 "identity.verified"）
      否则：     直接使用 state_value 本身
    """

    source: Literal["tool", "user"] = "user"
    state_key: str | None = None
    path: str | None = None
    transform: Callable[[Any], Any] | None = field(default=None, repr=False)
    description: str | None = None  # 仅 source="user" 时有意义，供 evaluator 向模型说明


# ── 阶段定义 ─────────────────────────────────────────────────────────────────


@dataclass
class StageDefinition:
    """阶段定义。

    required 语义:
      True（默认）: 必须阶段，无数据时阻塞后续阶段，视为当前阶段。
      False: 可跳过阶段，无数据时 status="skipped"，不阻塞后续推进。

    field_sources 语义:
      声明每个 output_schema 字段的数据来源。
      source="tool"：框架自动从 session.state 提取。
      source="user"：LLM 需从用户对话中收集，evaluator 会在响应中列出这些字段及说明。
      未声明 field_sources 时，CommitFlowStageTool 直接使用 user_data（兼容旧阶段）。

    reference_file: references/ 目录下的文件名（如 "identity_verify.md"）。
      Dynamic 注入模式以此为准，与 stage.id 解耦。
    """

    id: str
    name: str
    description: str
    required: bool = True
    output_schema: type[BaseModel] | None = None
    reference_file: str | None = None
    tools: list[str] = field(default_factory=list)
    field_sources: dict[str, FieldSource] = field(default_factory=dict)
    # checkpoint=True: 该阶段完成后触发 persist_flow_context 写盘，保留跨会话恢复点。
    # 无需每个阶段都持久化时，将非关键阶段设为 False 可减少 I/O。
    checkpoint: bool = False
    # delta_state_keys: 额外需要快照到 stage_delta 的 session.state 键。
    # 这些键不参与 field_sources 校验，仅用于 resume 时还原工具输出到 session.state，
    # 使下游工具（如 submit_withdrawal）在跨会话恢复后仍能读到原始数据。
    delta_state_keys: list[str] = field(default_factory=list)

    def user_required_fields(self) -> list[dict[str, str]]:
        """返回 source="user" 的字段列表，供 evaluator 响应向模型描述。"""
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


# ── 全局注册表 ───────────────────────────────────────────────────────────────


class FlowEvaluatorRegistry:
    """全局单例注册表，维护 skill_name → evaluator 实例映射。

    业务层在 Agent 初始化时 register()；
    框架层的 Dynamic reference 注入 / persist_flow_context hook 通过 get() 反查，
    无需硬编码 import。
    """

    _registry: dict[str, "BaseFlowEvaluator"] = {}

    @classmethod
    def register(cls, evaluator: "BaseFlowEvaluator") -> None:
        cls._registry[evaluator.skill_name] = evaluator

    @classmethod
    def get(cls, skill_name: str) -> "BaseFlowEvaluator | None":
        return cls._registry.get(skill_name)

    @classmethod
    def all(cls) -> dict[str, "BaseFlowEvaluator"]:
        return dict(cls._registry)


# ── BaseFlowEvaluator 抽象基类 ────────────────────────────────────────────────


class BaseFlowEvaluator(AgentTool, ABC):
    """流程评估器基类（框架层）。

    每个业务流程继承此类，仅需定义 skill_name 和 stages。
    基类提供通用的阶段遍历、Pydantic 校验、状态恢复等能力。

    当前阶段存在 source="user" 字段时，evaluator 在 JSON 响应中列出待收集字段，
    由模型自主决定何时收集并调用 commit_flow_stage，无需框架强制中断 ReAct 循环。

    工具 name 格式: "{skill_name}_evaluator"，避免多流程并存时名称冲突。
    SKILL.md frontmatter 中 required_tools 应写对应具体名称。
    """

    description = "评估当前流程进度，返回当前阶段、已完成步骤、下一步操作建议"
    parameters: list[ToolParameter] = []
    name: str = "flow_evaluator"  # overridden per instance in __init__

    def __init__(self) -> None:
        self.name = f"{self.skill_name}_evaluator"
        self._task_registry: TaskRegistry | None = None
        self._ttl_hours: int = 72

    @property
    @abstractmethod
    def skill_name(self) -> str:
        """关联的 SKILL 目录名，同时作为工具 name 前缀。"""
        ...

    @property
    @abstractmethod
    def stages(self) -> list[StageDefinition]:
        """子类必须定义阶段列表（有序）。"""
        ...

    async def execute(
        self, tool_call: ToolCall, context: dict[str, Any] | None = None
    ) -> AgentToolResult:
        ctx = context or {}
        flow_ctx: dict[str, Any] = dict(ctx.get("_flow_context") or {})

        # 本会话首次调用（无 flow_id）且配置了 task_registry：检查是否有待恢复任务。
        # 用 _pending_checked_{skill_name} 标记确保同一会话只检查一次，
        # 避免用户拒绝恢复后每次调用都重复提示。
        _pending_flag = f"_pending_checked_{self.skill_name}"
        if (
            not flow_ctx.get("flow_id")
            and self._task_registry is not None
            and not ctx.get(_pending_flag)
        ):
            user_id = str(ctx.get("user:id", ""))
            if user_id:
                active = self._task_registry.list_active(user_id, ttl_hours=self._ttl_hours)
                logger.debug("Active tasks: %s", active)
                pending = [t for t in active if t.get("skill_name") == self.skill_name]
                if pending:
                    task = pending[0]
                    return AgentToolResult(
                        tool_call_id=tool_call.id,
                        result_type=ToolResultType.JSON,
                        content={
                            "status": "pending_task_detected",
                            "pending_task": {
                                "flow_id": task["flow_id"],
                                "skill_name": task["skill_name"],
                                "current_stage": task["current_stage"],
                            },
                            "instruction": (
                                f"检测到用户有未完成的「{task['skill_name']}」任务"
                                f"（当前阶段：{task['current_stage']}）。"
                                f"请先向用户展示该任务，等待用户明确答复后再操作：\n"
                                f"  继续      → resume_task(flow_id=\"{task['flow_id']}\", action=\"resume\")\n"
                                f"  废弃      → resume_task(flow_id=\"{task['flow_id']}\", action=\"discard\")\n"
                                f"  重新开始  → resume_task(flow_id=\"{task['flow_id']}\", action=\"discard\")"
                                f"，然后重新发起流程\n"
                                f"⚠️ 严禁未得到用户答复前直接调用 resume_task。"
                            ),
                        },
                        metadata={"state_delta": {_pending_flag: True}},
                    )

        # 初始化 flow_id（首次调用）
        init_flow_ctx: dict[str, Any] | None = None
        if not flow_ctx.get("flow_id"):
            flow_ctx = {"flow_id": str(uuid.uuid4()), "skill_name": self.skill_name}
            init_flow_ctx = flow_ctx

        completed, is_done = self._evaluate_stages(flow_ctx)

        if is_done:
            state_delta: dict[str, Any] = {"_flow_stage": "__completed__"}
            if init_flow_ctx:
                state_delta["_flow_context"] = init_flow_ctx
            return AgentToolResult(
                tool_call_id=tool_call.id,
                result_type=ToolResultType.JSON,
                content={
                    "flow_status": "completed",
                    "completed_stages": completed,
                    "progress": f"{len(self.stages)}/{len(self.stages)}",
                    "instruction": "所有阶段已完成，流程结束。",
                },
                metadata={"state_delta": state_delta},
            )

        # 确定当前阶段
        if completed and completed[-1]["status"] == "incomplete":
            current_stage = self.stages[len(completed) - 1]
        else:
            current_stage = self.stages[len(completed)]

        state_delta = {"_flow_stage": current_stage.id}
        if init_flow_ctx:
            state_delta["_flow_context"] = init_flow_ctx

        # 若当前阶段有需要从用户收集的字段，列入响应供模型规划
        user_fields = current_stage.user_required_fields()

        current_stage_info: dict[str, Any] = {
            "id": current_stage.id,
            "name": current_stage.name,
            "description": current_stage.description,
            "suggested_tools": current_stage.tools,
        }
        if user_fields:
            current_stage_info["user_required_fields"] = user_fields

        # 将已记录的 checkpoint 列表暴露给 LLM，供回退决策使用
        available_checkpoints: list[dict[str, Any]] = list(flow_ctx.get("checkpoints") or [])

        return AgentToolResult(
            tool_call_id=tool_call.id,
            result_type=ToolResultType.JSON,
            content={
                "flow_status": "in_progress",
                "current_stage": current_stage_info,
                "completed_stages": completed,
                "progress": f"{len(completed)}/{len(self.stages)}",
                "available_checkpoints": available_checkpoints,
                "instruction": self._build_instruction(current_stage),
            },
            metadata={"state_delta": state_delta},
        )

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
                # 数据有但校验失败 → 当前阶段（需重做）
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

    def _build_instruction(self, stage: StageDefinition) -> str:
        user_fields = stage.user_required_fields()
        if user_fields:
            field_names = ", ".join(f['field'] for f in user_fields)
            return (
                f"当前处于【{stage.name}】阶段。"
                f"请按阶段参考文档完成准备工作（{stage.tools}），"
                f"向用户收集以下信息：{field_names}，"
                f"然后调用 commit_flow_stage 提交，再次调用 {self.name} 确认推进。"
            )
        return (
            f"当前处于【{stage.name}】阶段。"
            f"请根据当前阶段参考文档中的操作指引，"
            f"使用 {stage.tools} 完成此阶段，"
            f"然后再次调用 {self.name} 确认阶段完成。"
        )

    def get_restorable_state(self, flow_ctx: dict[str, Any]) -> dict[str, Any]:
        """序列化为可持久化格式（写入 active_tasks.json）。"""
        completed, is_done = self._evaluate_stages(flow_ctx)
        if is_done:
            current_stage_id = "__completed__"
        elif completed and completed[-1]["status"] == "incomplete":
            current_stage_id = completed[-1]["id"]
        else:
            current_stage_id = self.stages[len(completed)].id if len(completed) < len(self.stages) else "__completed__"

        return {
            "flow_id": flow_ctx.get("flow_id"),
            "skill_name": self.skill_name,
            "current_stage": current_stage_id,
            "stages": {
                stage.id: {
                    "status": "completed" if self._is_stage_complete(stage, flow_ctx) else "pending",
                    "data": flow_ctx.get(f"stage_{stage.id}", {}),
                    # delta: commit_flow_stage 提交时捕获的 source="tool" 原始 state 值，
                    # 供 resume_task 恢复后将其还原到 session.state 顶层，
                    # 使 render_a2ui 等下游工具在恢复后仍能读到原始工具输出。
                    "delta": flow_ctx.get(f"stage_{stage.id}_delta", {}),
                }
                for stage in self.stages
            },
        }

    def _is_stage_complete(self, stage: StageDefinition, flow_ctx: dict[str, Any]) -> bool:
        stage_data = flow_ctx.get(f"stage_{stage.id}", {})
        if not stage_data:
            return not stage.required  # 可跳过阶段视为完成
        valid, _ = stage.validate_output(stage_data)
        return valid
