"""Pre-compaction memory flush

在上下文压缩前，用 LLM 从完整对话历史中提取需要持久化的信息，
分流写入全局 profile (heading-based markdown) 和 agent memory (heading-based markdown)。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, TYPE_CHECKING

from .user_profile import load_user_profile, write_profile, upsert_profile_by_heading

if TYPE_CHECKING:
    from langchain_core.language_models.chat_models import BaseChatModel
    from ..types import AgentMessage
    from ..prompt.builder import PromptConfig
    from .manager import MemoryManager

logger = logging.getLogger(__name__)


@dataclass
class FlushResult:
    """Flush 提取结果"""

    profile: str = ""
    agent_memory: str = ""

    @property
    def has_content(self) -> bool:
        return bool(self.profile.strip()) or bool(self.agent_memory.strip())


_FLUSH_PROMPT = """\
你是一个记忆提取器。从以下对话历史中提取需要长期保存的信息。

当前智能体: {agent_name}
智能体职责: {agent_description}

当前用户画像:
{current_profile}

对话历史:
{conversation}

分类规则:
- profile (全局画像): 用户身份信息、沟通风格偏好、跨场景通用偏好。包括用户对 AI 行为的批评（如「太啰嗦」）——这类批评反映了用户的沟通偏好，必须作为 profile 记录并替换旧内容
- agent_memory (业务记忆): 与上述智能体职责直接相关的决策、偏好、事实、关键数据
- 不记录: 寒暄、一次性查询、临时计算、无持久化价值的内容

输出严格 JSON（不要包含 markdown 代码块标记）:
{{
  "profile": "完整的用户画像（heading-based markdown, 如 ## 用户姓名\\n张三），包含已有画像和新发现的信息",
  "agent_memory": "新发现的业务记忆（heading-based markdown, 如 ## 只看第一个保单\\n用户查询时只关注第一个保单），如无新内容则为空串"
}}
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
        current_profile: str,
        agent_name: str,
        agent_description: str,
    ) -> FlushResult:
        """调用 LLM 从完整对话中提取记忆。"""
        prompt = _FLUSH_PROMPT.format(
            agent_name=agent_name,
            agent_description=agent_description,
            current_profile=current_profile or "(空)",
            conversation=conversation_text[:8000],
        )

        llm = self._get_llm()
        response = await llm.ainvoke(prompt)
        raw = _extract_text_from_content(response.content)

        return self._parse_response(raw)

    def _parse_response(self, raw: str) -> FlushResult:
        """解析 LLM 返回的 JSON。"""
        if not raw or not raw.strip():
            return FlushResult()

        text = raw.strip()
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
            logger.debug("Memory flush returned non-JSON, skipping: %.100s", text)
            return FlushResult()

        if not isinstance(data, dict) or not data:
            return FlushResult()

        profile = str(data.get("profile", "")).strip()
        agent_memory = str(data.get("agent_memory", "")).strip()

        return FlushResult(profile=profile, agent_memory=agent_memory)

    async def save(
        self,
        result: FlushResult,
        profile_path: Path,
        agent_memory_path: Path,
    ) -> None:
        """将 flush 结果写入文件。Profile 全量覆写，agent_memory 追加。"""
        if result.profile:
            write_profile(
                profile_path.parent.parent.parent,
                profile_path.parent.name,
                result.profile,
            )
            logger.info("Flushed profile to %s", profile_path)
        if result.agent_memory:
            self._append_agent_memory(result.agent_memory, agent_memory_path)

    def save_profile_overwrite(self, profile_text: str, profile_path: Path) -> None:
        """全量覆写 profile 文件（flush 专用）。"""
        profile_path.parent.mkdir(parents=True, exist_ok=True)
        profile_path.write_text(profile_text, encoding="utf-8")
        logger.info("Flushed profile (overwrite) to %s", profile_path)

    def make_pre_compact_callback(
        self,
        user_id: str,
        prompt_config: "PromptConfig",
        memory_manager: "MemoryManager",
    ) -> Callable[[str, list["AgentMessage"]], Awaitable[None]]:
        """返回 pre_compact_callback 闭包，在压缩前全量提取记忆。"""

        async def _flush(session_id: str, messages: list["AgentMessage"]) -> None:
            try:
                from ..paths import get_memory_base_dir

                base_dir = get_memory_base_dir()
                current_profile = load_user_profile(base_dir, user_id)
                agent_name = prompt_config.agent_name or "assistant"
                agent_desc = prompt_config.agent_description or ""

                conversation_text = "\n".join(
                    f"{m.role.value}: {m.content or ''}" for m in messages if m.content
                )

                result = await self.flush(
                    conversation_text=conversation_text,
                    current_profile=current_profile,
                    agent_name=agent_name,
                    agent_description=agent_desc,
                )

                if result.has_content:
                    if result.profile:
                        write_profile(base_dir, user_id, result.profile)
                    if result.agent_memory:
                        ws = Path(memory_manager.config.workspace_dir) / user_id
                        agent_memory_path = ws / "MEMORY.md"
                        self._append_agent_memory(result.agent_memory, agent_memory_path)
                    memory_manager.mark_dirty()
                    logger.info("Pre-compaction memory flush completed for user %s", user_id)

            except Exception as e:
                logger.warning("Memory flush failed for user %s: %s", user_id, e)

        return _flush

    def _append_agent_memory(self, text: str, memory_path: Path) -> None:
        """追加 agent 记忆到 MEMORY.md body。"""
        memory_path.parent.mkdir(parents=True, exist_ok=True)
        with open(memory_path, "a", encoding="utf-8") as f:
            f.write(f"\n{text}\n")
        logger.info("Appended agent memory to %s", memory_path)
