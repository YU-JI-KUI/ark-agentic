"""异步后台记忆提取

每轮对话结束后，用 LLM 从对话中自动提取需要持久化的信息，
分流写入全局 profile (YAML frontmatter) 和 agent memory (MEMORY.md body)。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, TYPE_CHECKING

from .user_profile import read_frontmatter, write_frontmatter

if TYPE_CHECKING:
    from langchain_core.language_models.chat_models import BaseChatModel

logger = logging.getLogger(__name__)


@dataclass
class ExtractedMemory:
    """提取结果"""

    profile: dict[str, dict[str, str]] = field(default_factory=dict)
    agent_memory: str = ""

    @property
    def has_content(self) -> bool:
        return bool(self.profile) or bool(self.agent_memory)


_EXTRACTION_PROMPT = """\
从以下对话中提取需要持久化的信息。

当前智能体: {agent_name}
智能体职责: {agent_description}

分类规则:
- profile (全局画像): 用户身份信息、沟通风格偏好、跨场景通用偏好
  例: "我叫张三" → profile, "我喜欢简洁的回复" → profile
- agent_memory (业务记忆): 与上述智能体职责直接相关的决策、偏好、事实
  例: "只看第一个保单" → agent_memory, "不显示贷款选项" → agent_memory
- 不记录: 寒暄、一次性查询、无持久化价值的内容

当前用户画像:
{current_profile}

对话:
用户: {user_message}
助手: {assistant_response}

输出严格 JSON（不要包含 markdown 代码块标记）:
{{"profile": {{"section名": {{"key": "value"}}}}, "agent_memory": "需记录的文本或空串"}}
如果没有任何需要记录的内容，输出 {{}}
"""


class MemoryExtractor:
    """从对话中异步提取记忆

    通过 llm_factory 延迟获取 LLM 实例（DIP），
    避免在构造时绑定具体 LLM。
    """

    def __init__(self, llm_factory: Callable[[], BaseChatModel]) -> None:
        self._get_llm = llm_factory

    async def extract(
        self,
        user_message: str,
        assistant_response: str,
        current_profile: dict[str, Any],
        agent_name: str,
        agent_description: str,
    ) -> ExtractedMemory:
        """调用 LLM 提取记忆，返回结构化结果。"""
        from .user_profile import _format_profile

        profile_text = _format_profile(current_profile) or "(空)"

        prompt = _EXTRACTION_PROMPT.format(
            agent_name=agent_name,
            agent_description=agent_description,
            current_profile=profile_text,
            user_message=user_message,
            assistant_response=assistant_response[:1000],
        )

        llm = self._get_llm()
        response = await llm.ainvoke(prompt)
        raw = response.content if hasattr(response, "content") else str(response)

        return self._parse_response(raw)

    def _parse_response(self, raw: str) -> ExtractedMemory:
        """解析 LLM 返回的 JSON。容错处理非 JSON 输出。"""
        if not raw or not raw.strip():
            return ExtractedMemory()

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
            logger.debug("Memory extraction returned non-JSON, skipping: %.100s", text)
            return ExtractedMemory()

        if not isinstance(data, dict) or not data:
            return ExtractedMemory()

        profile = {}
        for section, entries in data.get("profile", {}).items():
            if isinstance(entries, dict):
                profile[str(section)] = {str(k): str(v) for k, v in entries.items()}

        agent_memory = str(data.get("agent_memory", "")).strip()

        return ExtractedMemory(profile=profile, agent_memory=agent_memory)

    async def save(
        self,
        result: ExtractedMemory,
        profile_path: Path,
        agent_memory_path: Path,
    ) -> None:
        """将提取结果写入对应文件。"""
        if result.profile:
            self._save_profile(result.profile, profile_path)
        if result.agent_memory:
            self._append_agent_memory(result.agent_memory, agent_memory_path)

    def _save_profile(
        self, profile_data: dict[str, dict[str, str]], profile_path: Path,
    ) -> None:
        """合并 profile 数据到 YAML frontmatter。"""
        existing = read_frontmatter(profile_path)

        for section, entries in profile_data.items():
            if section not in existing or not isinstance(existing.get(section), dict):
                existing[section] = {}
            existing[section].update(entries)

        write_frontmatter(profile_path, existing)
        count = sum(len(v) for v in profile_data.values())
        logger.info("Saved %d profile entries to %s", count, profile_path)

    def _append_agent_memory(self, text: str, memory_path: Path) -> None:
        """追加 agent 记忆到 MEMORY.md body。"""
        memory_path.parent.mkdir(parents=True, exist_ok=True)
        with open(memory_path, "a", encoding="utf-8") as f:
            f.write(f"\n{text}\n")
        logger.info("Appended agent memory to %s", memory_path)
