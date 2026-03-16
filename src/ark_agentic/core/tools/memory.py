"""
Memory 工具

提供 memory_search、memory_get 只读工具供 Agent 调用。
记忆写入由后台 MemoryExtractor 自动完成，无需 agent 显式调用。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, TYPE_CHECKING

from .base import AgentTool, ToolParameter, read_string_param, read_int_param, read_float_param
from ..types import AgentToolResult

if TYPE_CHECKING:
    from ..memory.manager import MemoryManager
    from ..types import ToolCall

logger = logging.getLogger(__name__)

MemoryProvider = Callable[[str], "MemoryManager | None"]


def _resolve_memory(provider: MemoryProvider, context: dict[str, Any] | None) -> "MemoryManager":
    user_id = (context or {}).get("user:id")
    if not user_id:
        raise ValueError("user:id is required in context for memory operations")
    mgr = provider(str(user_id))
    if mgr is None:
        raise ValueError("Memory system not available")
    return mgr


class MemorySearchTool(AgentTool):
    """Memory 语义搜索工具"""

    name = "memory_search"
    thinking_hint = "正在检索记忆库…"
    description = (
        "在 MEMORY.md 中进行语义搜索。"
        "在回答任何关于历史决策、日期、人员、偏好或上下文的问题之前，先使用此工具检索。"
        "返回最相关的片段及其文件路径和行号。"
    )
    parameters = [
        ToolParameter(
            name="query",
            type="string",
            description="搜索查询 - 描述你要查找的内容",
            required=True,
        ),
        ToolParameter(
            name="max_results",
            type="integer",
            description="最大返回结果数（默认: 6）",
            required=False,
            default=6,
        ),
        ToolParameter(
            name="min_score",
            type="number",
            description="最低相关性分数阈值 0-1（默认: 0.35）",
            required=False,
            default=0.35,
        ),
    ]

    def __init__(self, memory_provider: MemoryProvider) -> None:
        self._provider = memory_provider

    async def execute(
        self, tool_call: ToolCall, context: dict[str, Any] | None = None
    ) -> AgentToolResult:
        args = tool_call.arguments or {}
        query = read_string_param(args, "query", "")
        max_results = read_int_param(args, "max_results", 6)
        min_score = read_float_param(args, "min_score", 0.35)

        if not query:
            return AgentToolResult.json_result(
                tool_call_id=tool_call.id,
                data={"error": "Query is required", "results": []},
            )

        try:
            memory = _resolve_memory(self._provider, context)
            if not memory._initialized:
                await memory.initialize()

            results = await memory.search(
                query=query,
                max_results=int(max_results),
                min_score=float(min_score),
            )

            formatted = []
            for r in results:
                formatted.append({
                    "path": r.path,
                    "start_line": r.start_line,
                    "end_line": r.end_line,
                    "score": round(r.score, 3),
                    "snippet": r.snippet,
                    "citation": r.citation or f"{r.path}#L{r.start_line}",
                })

            logger.debug(f"Memory search '{query}': found {len(formatted)} results")

            return AgentToolResult.json_result(
                tool_call_id=tool_call.id,
                data={
                    "query": query,
                    "results": formatted,
                    "total": len(formatted),
                },
            )

        except Exception as e:
            logger.exception(f"Memory search error: {e}")
            return AgentToolResult.json_result(
                tool_call_id=tool_call.id,
                data={"error": str(e), "results": []},
            )


class MemoryGetTool(AgentTool):
    """Memory 文件读取工具"""

    name = "memory_get"
    thinking_hint = "正在读取记忆内容…"
    description = (
        "读取 MEMORY.md 中的指定行。"
        "在 memory_search 之后使用此工具获取结果的更多上下文。"
        "请保持请求量小以节省上下文窗口。"
    )
    parameters = [
        ToolParameter(
            name="path",
            type="string",
            description="记忆文件的相对路径（通常为 'MEMORY.md'）",
            required=True,
        ),
        ToolParameter(
            name="from_line",
            type="integer",
            description="起始行号（从 1 开始，默认: 1）",
            required=False,
            default=1,
        ),
        ToolParameter(
            name="lines",
            type="integer",
            description="读取行数（默认: 50，最大: 200）",
            required=False,
            default=50,
        ),
    ]

    def __init__(self, memory_provider: MemoryProvider) -> None:
        self._provider = memory_provider

    async def execute(
        self, tool_call: ToolCall, context: dict[str, Any] | None = None
    ) -> AgentToolResult:
        args = tool_call.arguments or {}
        rel_path = read_string_param(args, "path", "")
        from_line = read_int_param(args, "from_line", 1)
        num_lines = read_int_param(args, "lines", 50)

        if not rel_path:
            return AgentToolResult.json_result(
                tool_call_id=tool_call.id,
                data={"error": "Path is required", "path": "", "text": ""},
            )

        num_lines = min(int(num_lines), 200)
        from_line = max(1, int(from_line))

        try:
            memory = _resolve_memory(self._provider, context)
            workspace_dir = Path(memory.config.workspace_dir)
            file_path = workspace_dir / rel_path

            try:
                file_path = file_path.resolve()
                workspace_dir = workspace_dir.resolve()
                if not str(file_path).startswith(str(workspace_dir)):
                    return AgentToolResult.json_result(
                        tool_call_id=tool_call.id,
                        data={
                            "error": "Path must be within workspace",
                            "path": rel_path,
                            "text": "",
                        },
                    )
            except Exception:
                pass

            if not file_path.exists():
                return AgentToolResult.json_result(
                    tool_call_id=tool_call.id,
                    data={
                        "error": f"File not found: {rel_path}",
                        "path": rel_path,
                        "text": "",
                    },
                )

            content = file_path.read_text(encoding="utf-8")
            lines = content.split("\n")
            total_lines = len(lines)

            start_idx = from_line - 1
            end_idx = min(start_idx + num_lines, total_lines)
            selected_lines = lines[start_idx:end_idx]
            text = "\n".join(selected_lines)

            logger.debug(
                f"Memory get '{rel_path}': lines {from_line}-{end_idx} of {total_lines}"
            )

            return AgentToolResult.json_result(
                tool_call_id=tool_call.id,
                data={
                    "path": rel_path,
                    "from_line": from_line,
                    "to_line": end_idx,
                    "total_lines": total_lines,
                    "text": text,
                },
            )

        except Exception as e:
            logger.exception(f"Memory get error: {e}")
            return AgentToolResult.json_result(
                tool_call_id=tool_call.id,
                data={"error": str(e), "path": rel_path, "text": ""},
            )


def create_memory_tools(memory_provider: MemoryProvider) -> list[AgentTool]:
    """创建只读 memory 工具集

    Args:
        memory_provider: 根据 user_id 获取对应 MemoryManager 的回调

    Returns:
        [MemorySearchTool, MemoryGetTool]
    """
    return [
        MemorySearchTool(memory_provider),
        MemoryGetTool(memory_provider),
    ]
