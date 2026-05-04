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
from ..flow.base_evaluator import FlowEvaluatorRegistry
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
        """将 `flow_context_snapshot` 还原为运行时 `_flow_context`（扁平，与持久化同形）。

        期望与 `BaseFlowEvaluator.get_persistable_context(flow_ctx)` 写入的结构一致：
        flow_id / skill_name / current_stage / stage_<id> / stage_<id>_delta / checkpoints / …
        """
        snapshot: dict[str, Any] = dict(task.get("flow_context_snapshot") or {})
        snapshot.setdefault("flow_id", task["flow_id"])
        snapshot.setdefault("skill_name", task["skill_name"])
        snapshot.setdefault(
            "current_stage", task.get("current_stage", "__completed__")
        )
        for key in list(snapshot.keys()):
            if key.startswith("_user_input_"):
                snapshot.pop(key, None)
        return snapshot

    @staticmethod
    def _extract_delta_state(task: dict[str, Any]) -> dict[str, Any]:
        """从所有 `stage_*_delta` 合并到 session.state 顶层（后出现的 key 覆盖先前的）。"""
        snapshot: dict[str, Any] = dict(task.get("flow_context_snapshot") or {})
        ev = FlowEvaluatorRegistry.get(task.get("skill_name") or "")
        result: dict[str, Any] = {}
        if ev is not None:
            for state_key, raw in ev.iter_delta_state(snapshot):
                result[state_key] = raw
            return result
        for key, value in snapshot.items():
            if (
                key.startswith("stage_")
                and key.endswith("_delta")
                and isinstance(value, dict)
            ):
                result.update(value)
        return result
