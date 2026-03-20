"""
Memory 工具

提供 memory_search、memory_get、memory_write 工具供 Agent 调用。
- memory_search / memory_get: 检索和读取记忆
- memory_write: Agent 主动写入记忆（profile heading-upsert + agent_memory append）
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


def _get_user_id(context: dict[str, Any] | None) -> str:
    user_id = (context or {}).get("user:id")
    if not user_id:
        raise ValueError("user:id is required in context for memory operations")
    return str(user_id)


class MemorySearchTool(AgentTool):
    """Memory 语义搜索工具"""

    name = "memory_search"
    thinking_hint = "正在检索记忆库…"
    description = (
        "在记忆库中进行语义搜索。"
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
    """Memory DB 读取工具"""

    name = "memory_get"
    thinking_hint = "正在读取记忆内容…"
    description = (
        "读取记忆中的指定位置内容。"
        "在 memory_search 之后使用此工具获取结果的更多上下文。"
        "请保持请求量小以节省上下文窗口。"
    )
    parameters = [
        ToolParameter(
            name="path",
            type="string",
            description="记忆文件的相对路径（来自 memory_search 结果）",
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
        rel_path = read_string_param(args, "path", "") or ""
        from_line = read_int_param(args, "from_line", 1) or 1
        num_lines = read_int_param(args, "lines", 50) or 50

        if not rel_path:
            return AgentToolResult.json_result(
                tool_call_id=tool_call.id,
                data={"error": "Path is required", "path": "", "text": ""},
            )

        num_lines = min(int(num_lines), 200)
        from_line = max(1, int(from_line))

        try:
            user_id = _get_user_id(context)
            memory = _resolve_memory(self._provider, context)
            if not memory._initialized:
                await memory.initialize()

            store = memory._store
            if store is None:
                return AgentToolResult.json_result(
                    tool_call_id=tool_call.id,
                    data={"error": "Memory store not initialized", "path": rel_path, "text": ""},
                )

            chunks = store.get_chunks_by_location(
                user_id=user_id, path=rel_path,
                from_line=from_line, limit=num_lines,
            )

            if not chunks:
                return AgentToolResult.json_result(
                    tool_call_id=tool_call.id,
                    data={
                        "error": f"No chunks found for path: {rel_path}",
                        "path": rel_path,
                        "text": "",
                    },
                )

            text = "\n\n".join(c.text for c in chunks)
            min_line = min(c.start_line for c in chunks)
            max_line = max(c.end_line for c in chunks)

            logger.debug(
                f"Memory get '{rel_path}': {len(chunks)} chunks, lines {min_line}-{max_line}"
            )

            return AgentToolResult.json_result(
                tool_call_id=tool_call.id,
                data={
                    "path": rel_path,
                    "from_line": min_line,
                    "to_line": max_line,
                    "total_chunks": len(chunks),
                    "text": text,
                },
            )

        except Exception as e:
            logger.exception(f"Memory get error: {e}")
            return AgentToolResult.json_result(
                tool_call_id=tool_call.id,
                data={"error": str(e), "path": rel_path, "text": ""},
            )


class MemoryWriteTool(AgentTool):
    """Memory 写入工具 - Agent 主动保存记忆"""

    name = "memory_write"
    thinking_hint = "正在保存记忆…"
    description = (
        "保存信息到长期记忆。当你判断「这条消息改变了我对用户的认知、下次对话需要记住」时，"
        "必须调用此工具——无论用户是直接表达偏好，还是通过对你行为的批评间接透露偏好，"
        "还是做出了持久决策。内容使用 ## 标题 + 描述的 markdown 格式。"
    )
    parameters = [
        ToolParameter(
            name="type",
            type="string",
            description="'profile'(用户画像,按标题合并) 或 'agent_memory'(业务记忆,追加)",
            required=True,
            enum=["profile", "agent_memory"],
        ),
        ToolParameter(
            name="content",
            type="string",
            description="heading-based markdown 内容, 如 '## 用户姓名\\n张三'",
            required=True,
        ),
    ]

    def __init__(self, memory_provider: MemoryProvider) -> None:
        self._provider = memory_provider

    async def execute(
        self, tool_call: ToolCall, context: dict[str, Any] | None = None
    ) -> AgentToolResult:
        args = tool_call.arguments or {}
        memory_type = read_string_param(args, "type", "") or ""
        content = read_string_param(args, "content", "") or ""

        if memory_type not in ("profile", "agent_memory"):
            return AgentToolResult.json_result(
                tool_call_id=tool_call.id,
                data={"error": "type must be 'profile' or 'agent_memory'", "saved": False},
            )
        if not content.strip():
            return AgentToolResult.json_result(
                tool_call_id=tool_call.id,
                data={"error": "content is required", "saved": False},
            )

        try:
            user_id = _get_user_id(context)
            memory = _resolve_memory(self._provider, context)

            from ..paths import get_memory_base_dir
            base_dir = get_memory_base_dir()

            if memory_type == "profile":
                from ..memory.user_profile import upsert_profile_by_heading, get_profile_path
                profile_path = get_profile_path(base_dir, user_id)
                upsert_profile_by_heading(profile_path, content)
                logger.info("memory_write: profile upserted for user %s", user_id)
            else:
                agent_memory_path = Path(memory.config.workspace_dir) / "MEMORY.md"
                agent_memory_path.parent.mkdir(parents=True, exist_ok=True)
                with open(agent_memory_path, "a", encoding="utf-8") as f:
                    f.write(f"\n{content}\n")
                memory.mark_dirty()
                logger.info("memory_write: agent_memory appended for user %s", user_id)

            return AgentToolResult.json_result(
                tool_call_id=tool_call.id,
                data={"saved": True, "type": memory_type},
            )

        except Exception as e:
            logger.exception(f"Memory write error: {e}")
            return AgentToolResult.json_result(
                tool_call_id=tool_call.id,
                data={"error": str(e), "saved": False},
            )


def create_memory_tools(memory_provider: MemoryProvider) -> list[AgentTool]:
    """创建 memory 工具集

    Args:
        memory_provider: 根据 user_id 获取对应 MemoryManager 的回调

    Returns:
        [MemorySearchTool, MemoryGetTool, MemoryWriteTool]
    """
    return [
        MemorySearchTool(memory_provider),
        MemoryGetTool(memory_provider),
        MemoryWriteTool(memory_provider),
    ]
