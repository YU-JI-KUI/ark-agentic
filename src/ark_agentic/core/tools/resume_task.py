"""ResumeTaskTool — 恢复或废弃中断流程任务。

Agent 调用此工具时，根据 action 参数执行对应操作：
  - action="resume"（默认）：从 active_tasks.json 还原 _flow_context 到当前 session，
    使 flow_evaluator 能从上次中断的阶段继续执行。
  - action="discard"：从 active_tasks.json 删除该任务记录，
    供用户选择废弃或重新开始时使用。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .base import AgentTool, ToolParameter
from ..types import AgentToolResult, ToolCall, ToolResultType

logger = logging.getLogger(__name__)


class ResumeTaskTool(AgentTool):
    """恢复或废弃用户之前未完成的业务流程。"""

    name = "resume_task"
    description = (
        "操作用户之前未完成的业务流程。"
        "action=resume：将流程进度恢复到当前会话，继续执行；"
        "action=discard：废弃该任务，从待恢复列表中移除。"
    )
    parameters = [
        ToolParameter(
            name="flow_id",
            type="string",
            required=True,
            description="要操作的流程 ID（从系统提示中的 flow_id 获取）",
        ),
        ToolParameter(
            name="action",
            type="string",
            required=False,
            enum=["resume", "discard"],
            description=(
                "resume（默认）：恢复流程进度并继续执行；"
                "discard：废弃任务，从待恢复列表永久移除。"
                "用户选择「重新开始」时也使用 discard，废弃后重新发起流程即可。"
            ),
        ),
    ]

    def __init__(self, sessions_dir: str | Path) -> None:
        self._sessions_dir = Path(sessions_dir)

    async def execute(
        self, tool_call: ToolCall, context: dict[str, Any] | None = None
    ) -> AgentToolResult:
        from ..flow.task_registry import TaskRegistry

        args = tool_call.arguments
        flow_id = args.get("flow_id", "").strip()
        if not flow_id:
            return AgentToolResult.error_result(tool_call.id, "flow_id 不能为空")

        action = (args.get("action") or "resume").strip().lower()
        if action not in ("resume", "discard"):
            return AgentToolResult.error_result(
                tool_call.id, f"action 无效：'{action}'，可选值为 resume / discard"
            )

        user_id = (context or {}).get("user:id")
        if not user_id:
            return AgentToolResult.error_result(tool_call.id, "无法获取 user_id，操作失败")

        registry = TaskRegistry(base_dir=self._sessions_dir)
        task = registry.get(str(user_id), flow_id)
        if not task:
            return AgentToolResult.error_result(
                tool_call.id, f"未找到流程记录: flow_id={flow_id}"
            )

        if action == "discard":
            return self._handle_discard(tool_call, registry, str(user_id), flow_id, task)

        return self._handle_resume(tool_call, task)

    def _handle_resume(
        self, tool_call: ToolCall, task: dict[str, Any]
    ) -> AgentToolResult:
        """恢复流程：还原 _flow_context 和各阶段 delta 到 session.state。"""
        restored_flow_ctx = self._snapshot_to_flow_context(task)
        restored_tool_state = self._extract_delta_state(task)

        state_delta: dict[str, Any] = {"_flow_context": restored_flow_ctx}
        state_delta.update(restored_tool_state)

        return AgentToolResult(
            tool_call_id=tool_call.id,
            result_type=ToolResultType.JSON,
            content={
                "status": "resumed",
                "flow_id": task["flow_id"],
                "skill_name": task.get("skill_name"),
                "current_stage": task.get("current_stage"),
                "message": (
                    f"已恢复【{task.get('skill_name')}】流程，"
                    f"当前在【{task.get('current_stage')}】阶段。"
                ),
            },
            metadata={"state_delta": state_delta},
        )

    def _handle_discard(
        self,
        tool_call: ToolCall,
        registry: Any,
        user_id: str,
        flow_id: str,
        task: dict[str, Any],
    ) -> AgentToolResult:
        """废弃流程：从 active_tasks.json 删除记录。"""
        try:
            registry.remove(user_id, flow_id)
            logger.info("Task discarded: flow_id=%s user_id=%s", flow_id, user_id)
        except Exception as e:
            logger.warning("Failed to discard task flow_id=%s: %s", flow_id, e)
            return AgentToolResult.error_result(tool_call.id, f"废弃任务失败: {e}")

        skill_name = task.get("skill_name", "")
        # 清空 _flow_context：防止 persist_flow_context 在本轮 after_agent 阶段
        # 用旧数据把刚删除的任务记录重新写回。pending 检测已改为每轮直检 registry，
        # 不再依赖 _pending_checked_<skill> flag，因此无需在此重置。
        state_delta: dict[str, Any] = {"_flow_context": {}}

        return AgentToolResult(
            tool_call_id=tool_call.id,
            result_type=ToolResultType.JSON,
            content={
                "status": "discarded",
                "flow_id": flow_id,
                "skill_name": skill_name,
                "message": (
                    f"【{skill_name}】流程已废弃。"
                    f"如需重新开始，请重新发起该业务流程。"
                ),
            },
            metadata={"state_delta": state_delta},
        )

    @staticmethod
    def _snapshot_to_flow_context(task: dict[str, Any]) -> dict[str, Any]:
        """将 active_tasks.json snapshot 格式转换回 _flow_context 运行时格式。

        snapshot 格式（get_restorable_state 产出）:
            {
              "flow_id": "...",
              "stages": {
                "identity_verify": {"status": "completed", "data": {...}, "delta": {...}},
                ...
              }
            }

        _flow_context 运行时格式（evaluator 读取）:
            {
              "flow_id": "...",
              "skill_name": "...",
              "stage_identity_verify": {...},        # 展平，key = stage_{id}
              "stage_identity_verify_delta": {...},  # 原始工具输出快照，key = stage_{id}_delta
              ...
            }
        """
        snapshot = task.get("flow_context_snapshot", {})
        flow_ctx: dict[str, Any] = {
            "flow_id": task["flow_id"],
            "skill_name": task["skill_name"],
        }
        for stage_id, stage_info in snapshot.get("stages", {}).items():
            if stage_info.get("status") == "completed" and stage_info.get("data"):
                flow_ctx[f"stage_{stage_id}"] = stage_info["data"]
            if stage_info.get("delta"):
                flow_ctx[f"stage_{stage_id}_delta"] = stage_info["delta"]

        # 从已完成的 checkpoint 阶段重建 checkpoints 历史，
        # 使 rollback_flow_stage 在 resume 后仍能获取有效回退点列表。
        from ..flow.base_evaluator import FlowEvaluatorRegistry
        evaluator = FlowEvaluatorRegistry.get(task["skill_name"])
        if evaluator:
            checkpoints = [
                {"stage_id": s.id, "name": s.name, "description": s.description}
                for s in evaluator.stages
                if s.checkpoint
                and snapshot.get("stages", {}).get(s.id, {}).get("status") == "completed"
            ]
            if checkpoints:
                flow_ctx["checkpoints"] = checkpoints

        return flow_ctx

    @staticmethod
    def _extract_delta_state(task: dict[str, Any]) -> dict[str, Any]:
        """从所有已完成阶段的 delta 中提取原始工具 state 键，还原到 session.state 顶层。

        这样 render_a2ui 等通过 state_keys 读取工具输出的工具，
        在流程恢复后仍能在 session.state 中找到所需数据。

        只处理 status="completed" 的阶段；delta 键发生冲突时后续阶段覆盖前序阶段。
        旧格式快照（无 delta 字段）降级为空 dict，保持向后兼容。
        """
        snapshot = task.get("flow_context_snapshot", {})
        result: dict[str, Any] = {}
        for stage_info in snapshot.get("stages", {}).values():
            if stage_info.get("status") == "completed":
                result.update(stage_info.get("delta", {}))
        return result
