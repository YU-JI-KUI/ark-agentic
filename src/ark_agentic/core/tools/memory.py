"""
Memory 工具

提供 memory_search 和 memory_get 工具供 Agent 调用。

参考: openclaw-main/src/agents/tools/memory-tool.ts
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, TYPE_CHECKING

from .base import AgentTool, ToolParameter, read_string_param, read_int_param, read_float_param
from ..types import AgentToolResult

if TYPE_CHECKING:
    from ..memory.manager import MemoryManager
    from ..types import ToolCall

logger = logging.getLogger(__name__)


class MemorySearchTool(AgentTool):
    """Memory 语义搜索工具

    搜索 MEMORY.md 和 memory/*.md 文件中的相关内容。
    使用混合搜索（向量 + 关键词）获取最相关的记忆片段。

    参考: openclaw-main/src/agents/tools/memory-tool.ts - createMemorySearchTool
    """

    name = "memory_search"
    thinking_hint = "正在检索记忆库…"
    description = (
        "Semantically search MEMORY.md and memory/*.md files. "
        "Use this tool BEFORE answering questions about prior work, decisions, "
        "dates, people, preferences, context, or any historical information. "
        "Returns top matching snippets with file paths and line numbers."
    )
    parameters = [
        ToolParameter(
            name="query",
            type="string",
            description="Search query - describe what you're looking for",
            required=True,
        ),
        ToolParameter(
            name="max_results",
            type="integer",
            description="Maximum number of results to return (default: 6)",
            required=False,
            default=6,
        ),
        ToolParameter(
            name="min_score",
            type="number",
            description="Minimum relevance score threshold 0-1 (default: 0.35)",
            required=False,
            default=0.35,
        ),
    ]

    def __init__(self, memory_manager: MemoryManager) -> None:
        self._memory = memory_manager

    async def execute(
        self, tool_call: ToolCall, context: dict[str, Any] | None = None
    ) -> AgentToolResult:
        """执行记忆搜索"""
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
            # 确保 memory manager 已初始化
            if not self._memory._initialized:
                await self._memory.initialize()

            results = await self._memory.search(
                query=query,
                max_results=int(max_results),
                min_score=float(min_score),
            )

            # 格式化结果
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
    """Memory 文件读取工具

    读取 memory 文件的指定行范围。配合 memory_search 使用，
    在搜索到相关片段后获取更多上下文。

    参考: openclaw-main/src/agents/tools/memory-tool.ts - createMemoryGetTool
    """

    name = "memory_get"
    thinking_hint = "正在读取记忆内容…"
    description = (
        "Read specific lines from a memory file (MEMORY.md or memory/*.md). "
        "Use this after memory_search to get more context around a result. "
        "Keep requests small to preserve context window."
    )
    parameters = [
        ToolParameter(
            name="path",
            type="string",
            description="Relative path to the memory file (e.g., 'MEMORY.md' or 'memory/project.md')",
            required=True,
        ),
        ToolParameter(
            name="from_line",
            type="integer",
            description="Starting line number (1-indexed, default: 1)",
            required=False,
            default=1,
        ),
        ToolParameter(
            name="lines",
            type="integer",
            description="Number of lines to read (default: 50, max: 200)",
            required=False,
            default=50,
        ),
    ]

    def __init__(self, memory_manager: MemoryManager) -> None:
        self._memory = memory_manager

    async def execute(
        self, tool_call: ToolCall, context: dict[str, Any] | None = None
    ) -> AgentToolResult:
        """读取 memory 文件"""
        args = tool_call.arguments or {}
        rel_path = read_string_param(args, "path", "")
        from_line = read_int_param(args, "from_line", 1)
        num_lines = read_int_param(args, "lines", 50)

        if not rel_path:
            return AgentToolResult.json_result(
                tool_call_id=tool_call.id,
                data={"error": "Path is required", "path": "", "text": ""},
            )

        # 限制行数
        num_lines = min(int(num_lines), 200)
        from_line = max(1, int(from_line))

        try:
            # 构建完整路径
            workspace_dir = Path(self._memory.config.workspace_dir)
            file_path = workspace_dir / rel_path

            # 安全检查：确保在 workspace 内
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

            # 读取文件
            content = file_path.read_text(encoding="utf-8")
            lines = content.split("\n")
            total_lines = len(lines)

            # 提取指定行范围
            start_idx = from_line - 1  # 转换为 0-indexed
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


class MemorySetTool(AgentTool):
    """Memory 写入工具

    将重要信息持久化写入 memory 文件。
    Agent 可以在对话中主动记录关键决策、用户偏好等，
    确保 compaction 后这些信息不会丢失。

    参考: openclaw-main/src/agents/tools/memory-tool.ts - memory_set
    """

    name = "memory_set"
    thinking_hint = "正在保存关键记忆…"
    description = (
        "Write important information to a memory file for long-term persistence. "
        "Use this to save key decisions, user preferences, action items, "
        "or any context that should survive conversation compaction. "
        "Content is appended to the specified memory file."
    )
    parameters = [
        ToolParameter(
            name="path",
            type="string",
            description=(
                "Relative path to the memory file "
                "(e.g., 'MEMORY.md' or 'memory/decisions.md'). "
                "File will be created if it doesn't exist."
            ),
            required=True,
        ),
        ToolParameter(
            name="content",
            type="string",
            description="Content to append to the memory file (markdown format recommended)",
            required=True,
        ),
        ToolParameter(
            name="section",
            type="string",
            description="Optional section heading to append under (e.g., '## Decisions')",
            required=False,
        ),
    ]

    def __init__(self, memory_manager: MemoryManager) -> None:
        self._memory = memory_manager

    async def execute(
        self, tool_call: ToolCall, context: dict[str, Any] | None = None
    ) -> AgentToolResult:
        """写入 memory 文件"""
        args = tool_call.arguments or {}
        rel_path = read_string_param(args, "path", "")
        content = read_string_param(args, "content", "")
        section = read_string_param(args, "section")

        if not rel_path:
            return AgentToolResult.error_result(
                tool_call.id, "Path is required"
            )
        if not content:
            return AgentToolResult.error_result(
                tool_call.id, "Content is required"
            )

        try:
            workspace_dir = Path(self._memory.config.workspace_dir)
            file_path = workspace_dir / rel_path

            # 安全检查：确保在 workspace 内
            try:
                file_path = file_path.resolve()
                workspace_resolved = workspace_dir.resolve()
                if not str(file_path).startswith(str(workspace_resolved)):
                    return AgentToolResult.error_result(
                        tool_call.id, "Path must be within workspace"
                    )
            except Exception:
                pass

            # 确保目录存在
            file_path.parent.mkdir(parents=True, exist_ok=True)

            # 构建要追加的文本
            append_text = "\n"
            if section:
                append_text += f"\n{section}\n\n"
            append_text += content + "\n"

            # 追加写入
            with open(file_path, "a", encoding="utf-8") as f:
                f.write(append_text)

            logger.info(f"Memory set: appended to {rel_path}")

            # 触发增量同步，使新内容可被 memory_search 检索
            try:
                if self._memory._initialized:
                    await self._memory.sync()
                    logger.debug(f"Memory index synced after writing to {rel_path}")
            except Exception as sync_err:
                logger.warning(f"Memory sync after set failed: {sync_err}")

            return AgentToolResult.json_result(
                tool_call_id=tool_call.id,
                data={
                    "path": rel_path,
                    "status": "written",
                    "bytes_written": len(append_text.encode("utf-8")),
                },
            )

        except Exception as e:
            logger.exception(f"Memory set error: {e}")
            return AgentToolResult.error_result(tool_call.id, str(e))


def create_memory_tools(memory_manager: MemoryManager) -> list[AgentTool]:
    """创建 memory 工具集

    Args:
        memory_manager: MemoryManager 实例

    Returns:
        [MemorySearchTool, MemoryGetTool, MemorySetTool]
    """
    return [
        MemorySearchTool(memory_manager),
        MemoryGetTool(memory_manager),
        MemorySetTool(memory_manager),
    ]
