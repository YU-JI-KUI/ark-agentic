"""ResumeTaskTool — 恢复中断流程任务。

Agent 调用此工具时，从 active_tasks.json 还原 _flow_context 到当前 session，
使 flow_evaluator 能从上次中断的阶段继续执行。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .base import AgentTool, ToolParameter
from ..types import AgentToolResult, ToolCall, ToolResultType

logger = logging.getLogger(__name__)


class ResumeTaskTool(AgentTool):
    """恢复用户之前未完成的业务流程，将之前的进度加载到当前会话。"""

    name = "resume_task"
    description = "恢复用户之前未完成的业务流程，将之前的进度加载到当前会话"
    parameters = [
        ToolParameter(
            name="flow_id",
            type="string",
            required=True,
            description="要恢复的流程 ID（从系统提示中的 flow_id 获取）",
        ),
    ]

    def __init__(self, sessions_dir: str | Path) -> None:
        self._sessions_dir = Path(sessions_dir)

    async def execute(
        self, tool_call: ToolCall, context: dict[str, Any] | None = None
    ) -> AgentToolResult:
        from ..flow.task_registry import TaskRegistry

        flow_id = tool_call.arguments.get("flow_id", "").strip()
        if not flow_id:
            return AgentToolResult.error_result(tool_call.id, "flow_id 不能为空")

        user_id = (context or {}).get("user:id")
        if not user_id:
            return AgentToolResult.error_result(tool_call.id, "无法获取 user_id，恢复失败")

        registry = TaskRegistry(base_dir=self._sessions_dir)
        task = registry.get(str(user_id), flow_id)
        if not task:
            return AgentToolResult.error_result(
                tool_call.id, f"未找到流程记录: flow_id={flow_id}"
            )

        restored_flow_ctx = self._snapshot_to_flow_context(task)
        restored_tool_state = self._extract_delta_state(task)

        # 同时还原 _flow_context（stage data）和各阶段工具原始输出（delta keys）
        state_delta: dict[str, Any] = {"_flow_context": restored_flow_ctx}
        state_delta.update(restored_tool_state)

        return AgentToolResult(
            tool_call_id=tool_call.id,
            result_type=ToolResultType.JSON,
            content={
                "status": "restored",
                "flow_id": flow_id,
                "skill_name": task.get("skill_name"),
                "current_stage": task.get("current_stage"),
                "message": (
                    f"已恢复【{task.get('skill_name')}】流程，"
                    f"当前在【{task.get('current_stage')}】阶段，"
                    f"请调用对应的 flow_evaluator 查看当前进度。"
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
