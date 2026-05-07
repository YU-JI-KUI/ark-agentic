"""
MetaBuilder Agent — 内置对话式 Agent 构建助手。

BaseAgent 子类。声明式身份 + ClassVar 行为旋钮 + 三个复合工具
（manage_agents / manage_skills / manage_tools）。
"""

from __future__ import annotations

import logging

from ark_agentic import BaseAgent
from ark_agentic.core.llm.sampling import SamplingConfig
from ark_agentic.core.session.compaction import CompactionConfig
from ark_agentic.core.types import SkillLoadMode

from .tools.manage_agents import ManageAgentsTool
from .tools.manage_skills import ManageSkillsTool
from .tools.manage_tools import ManageToolsTool

logger = logging.getLogger(__name__)


class MetaBuilderAgent(BaseAgent):
    """Ark-Agentic 内置 Meta-Agent — 通过自然语言创建 Agent / Skill / Tool。"""

    agent_id = "meta_builder"
    agent_name = "Ark-Agentic Meta-Agent"
    agent_description = (
        "你是一个 AI 构建助手，帮助开发者通过自然语言创建和管理 Agent、Skill 和 Tool。"
        "你拥有直接操作文件系统的工具，可以立即将创建结果持久化到磁盘。"
    )
    skill_load_mode = SkillLoadMode.full
    max_turns = 8

    def build_tools(self):
        return [ManageAgentsTool(), ManageSkillsTool(), ManageToolsTool()]

    def build_sampling(self) -> SamplingConfig:
        # Build tasks: low temperature + precise tool calls (slightly raised
        # to avoid over-determinism causing repeated outputs).
        return SamplingConfig.for_chat(temperature=0.3)

    def build_compaction(self) -> CompactionConfig:
        return CompactionConfig(context_window=64_000, preserve_recent=4)
