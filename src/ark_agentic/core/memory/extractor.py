"""Pre-compaction memory flush

在上下文压缩前，用 LLM 从完整对话历史中提取需要持久化的信息，
写入用户 MEMORY.md（heading-based markdown）。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Awaitable, Callable, TYPE_CHECKING

from pydantic import BaseModel

from .user_profile import upsert_profile_by_heading
from ..compaction import estimate_tokens

if TYPE_CHECKING:
    from langchain_core.language_models.chat_models import BaseChatModel
    from ..types import AgentMessage
    from ..prompt.builder import PromptConfig
    from .manager import MemoryManager

logger = logging.getLogger(__name__)

_MAX_FLUSH_TOKENS = 6000


class FlushResult(BaseModel):
    """Flush 提取结果"""

    memory: str = ""

    @property
    def has_content(self) -> bool:
        return bool(self.memory.strip())


_FLUSH_PROMPT = """\
你是一个记忆提取器。从以下对话历史中提取需要长期保存的信息。

当前智能体: {agent_name}
智能体职责: {agent_description}

当前用户记忆:
{current_memory}

对话历史:
{conversation}

分类规则:
- 记录: 用户身份信息、沟通风格偏好、业务决策、持久偏好、关键事实
- 不记录: 寒暄、一次性查询、临时计算、当前记忆中已有且未变化的内容

**仅输出新发现或需要更新的信息。不要重复当前记忆中未变化的内容。**

输出严格 JSON（不要包含 markdown 代码块标记）:
{{"memory": "新/变更的记忆（heading-based markdown, 如 ## 标题\\n内容），如无新内容则为空串"}}
如果没有任何需要记录的内容，输出 {{}}
"""


def _extract_text_from_content(content: object) -> str:
    """从 LLM response.content 提取文本，处理 list 类型（thinking models）。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in content
        )
    return str(content) if content else ""


def parse_llm_json(raw: str) -> dict[str, Any] | None:
    """Strip optional code-fence wrapper and parse JSON dict. Returns None on failure."""
    text = raw.strip()
    if not text:
        return None

    if "```" in text:
        for block in text.split("```"):
            block = block.strip()
            if block.startswith("json"):
                block = block[4:].strip()
            if block.startswith("{"):
                text = block
                break

    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None

    return data if isinstance(data, dict) else None


class MemoryFlusher:
    """Pre-compaction memory flush

    在上下文压缩前，从完整对话中提取记忆。
    通过 llm_factory 延迟获取 LLM 实例（DIP）。
    """

    def __init__(self, llm_factory: Callable[[], "BaseChatModel"]) -> None:
        self._get_llm = llm_factory

    async def flush(
        self,
        conversation_text: str,
        current_memory: str,
        agent_name: str,
        agent_description: str,
    ) -> FlushResult:
        """调用 LLM 从完整对话中提取记忆。"""
        tokens = estimate_tokens(conversation_text)
        if tokens > _MAX_FLUSH_TOKENS:
            ratio = _MAX_FLUSH_TOKENS / tokens
            conversation_text = conversation_text[-int(len(conversation_text) * ratio):]

        prompt = _FLUSH_PROMPT.format(
            agent_name=agent_name,
            agent_description=agent_description,
            current_memory=current_memory or "(空)",
            conversation=conversation_text,
        )

        llm = self._get_llm()
        response = await llm.ainvoke(prompt)
        raw = _extract_text_from_content(response.content)

        return self._parse_response(raw)

    def _parse_response(self, raw: str) -> FlushResult:
        """解析 LLM 返回的 JSON。"""
        data = parse_llm_json(raw)
        if not data:
            if raw and raw.strip():
                logger.debug("Memory flush returned non-JSON, skipping: %.100s", raw.strip())
            return FlushResult()

        memory = str(data.get("memory", "")).strip()
        return FlushResult(memory=memory)

    async def save(self, result: FlushResult, memory_path: Path) -> None:
        """Write flush result to user's MEMORY.md with heading upsert."""
        if result.memory:
            memory_path.parent.mkdir(parents=True, exist_ok=True)
            upsert_profile_by_heading(memory_path, result.memory)
            logger.info("Flushed memory to %s", memory_path)

    def make_pre_compact_callback(
        self,
        user_id: str,
        prompt_config: "PromptConfig",
        memory_manager: "MemoryManager",
    ) -> Callable[[str, list["AgentMessage"]], Awaitable[None]]:
        """返回 pre_compact_callback 闭包，在压缩前全量提取记忆。"""

        async def _flush(session_id: str, messages: list["AgentMessage"]) -> None:
            try:
                current_memory = memory_manager.read_memory(user_id)
                memory_path = memory_manager.memory_path(user_id)

                agent_name = prompt_config.agent_name or "assistant"
                agent_desc = prompt_config.agent_description or ""

                conversation_text = "\n".join(
                    f"{m.role.value}: {m.content or ''}" for m in messages if m.content
                )

                result = await self.flush(
                    conversation_text=conversation_text,
                    current_memory=current_memory,
                    agent_name=agent_name,
                    agent_description=agent_desc,
                )

                if result.has_content:
                    await self.save(result, memory_path)
                    logger.info("Pre-compaction memory flush completed for user %s", user_id)

            except Exception as e:
                logger.warning("Memory flush failed for user %s: %s", user_id, e)

        return _flush
