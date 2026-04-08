"""Memory 工具

提供 memory_write 工具供 Agent 主动保存用户记忆。
MEMORY.md 已注入 system prompt，无需 search/get 工具。
"""

from __future__ import annotations

import logging
from typing import Any, Callable, TYPE_CHECKING

from .base import AgentTool, ToolParameter, read_string_param
from ..types import AgentToolResult

if TYPE_CHECKING:
    from ..memory.manager import MemoryManager
    from ..types import ToolCall

logger = logging.getLogger(__name__)

MemoryProvider = Callable[[str], "MemoryManager | None"]


def _get_user_id(context: dict[str, Any] | None) -> str:
    user_id = (context or {}).get("user:id")
    if not user_id:
        raise ValueError("user:id is required in context for memory operations")
    return str(user_id)


def _resolve_memory(provider: MemoryProvider, context: dict[str, Any] | None) -> "MemoryManager":
    user_id = _get_user_id(context)
    mgr = provider(str(user_id))
    if mgr is None:
        raise ValueError("Memory system not available")
    return mgr


class MemoryWriteTool(AgentTool):
    """Memory 写入工具 — Agent 增量更新用户记忆"""

    name = "memory_write"
    thinking_hint = "正在保存记忆…"
    description = (
        "增量更新长期记忆。只需写你要新增、修改或删除的标题，其他标题不受影响。"
        "同名标题自动覆盖。删除错误标题：写入空内容（如 '## 错误标题\\n'）即可自动移除。"
        "写入前先检查上下文中 MEMORY.md 已有标题，避免创建语义重复的新标题。"
    )
    parameters = [
        ToolParameter(
            name="content",
            type="string",
            description=(
                "要新增/修改/删除的 heading-based markdown。"
                "只写变化的部分，如：'## 回复风格\\n简洁直接'。"
                "删除标题：写空内容，如 '## 贷款偏好\\n'。"
                "可一次写多个标题。"
            ),
            required=True,
        ),
    ]

    def __init__(self, memory_provider: MemoryProvider) -> None:
        self._provider = memory_provider

    async def execute(
        self, tool_call: "ToolCall", context: dict[str, Any] | None = None
    ) -> AgentToolResult:
        args = tool_call.arguments or {}
        content = read_string_param(args, "content", "") or ""

        if not content.strip():
            return AgentToolResult.json_result(
                tool_call_id=tool_call.id,
                data={"error": "content is required", "saved": False},
            )

        try:
            user_id = _get_user_id(context)
            memory = _resolve_memory(self._provider, context)
            current_headings, dropped = memory.write_memory(user_id, content)

            if not current_headings and not dropped:
                return AgentToolResult.json_result(
                    tool_call_id=tool_call.id,
                    data={
                        "saved": False,
                        "error": "Content must contain ## headings (e.g. '## 回复风格\\n简洁')",
                    },
                )

            data: dict[str, Any] = {
                "saved": True,
                "current_headings": current_headings,
            }
            if dropped:
                data["dropped_headings"] = dropped

            logger.info("memory_write: upserted for user %s, headings=%s", user_id, current_headings)
            return AgentToolResult.json_result(tool_call_id=tool_call.id, data=data)

        except Exception as e:
            logger.exception("Memory write error: %s", e)
            return AgentToolResult.json_result(
                tool_call_id=tool_call.id,
                data={"error": str(e), "saved": False},
            )


def create_memory_tools(memory_provider: MemoryProvider) -> list[AgentTool]:
    """创建 memory 工具集（仅 memory_write）。"""
    return [MemoryWriteTool(memory_provider)]
