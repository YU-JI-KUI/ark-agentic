"""
系统提示构建器

参考: openclaw-main/src/agents/system-prompt.ts
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ..skills.base import SkillConfig, render_skill_section
from ..tools.base import AgentTool
from ..types import SkillEntry

logger = logging.getLogger(__name__)


@dataclass
class PromptConfig:
    """提示配置"""

    # 基础信息
    agent_name: str = "Assistant"
    agent_description: str = "A helpful AI assistant"

    # 运行时信息
    include_datetime: bool = True
    include_timezone: bool = True
    timezone: str = "Asia/Shanghai"

    # 模型信息
    include_model_info: bool = False
    model_name: str = ""

    # 自定义指令
    custom_instructions: str = ""

    # 工具描述
    include_tool_descriptions: bool = True

    # <think>/<final> 标签指引（非空时注入到 system prompt）
    thinking_tag_instructions: str = ""



class SystemPromptBuilder:
    """系统提示构建器

    动态构建 LLM 的系统提示，包含：
    - 基础身份描述
    - 运行时信息
    - 工具描述
    - 技能指令
    - 自定义指令
    """

    def __init__(self, config: PromptConfig | None = None) -> None:
        self.config = config or PromptConfig()
        self._sections: list[tuple[str, str]] = []  # (section_name, content)

    def reset(self) -> SystemPromptBuilder:
        """重置构建器"""
        self._sections = []
        return self

    def add_section(self, name: str, content: str) -> SystemPromptBuilder:
        """添加自定义部分"""
        if content.strip():
            self._sections.append((name, content.strip()))
        return self

    def add_identity(
        self,
        name: str | None = None,
        description: str | None = None,
    ) -> SystemPromptBuilder:
        """添加身份描述"""
        agent_name = name or self.config.agent_name
        agent_desc = description or self.config.agent_description

        content = f"You are {agent_name}. {agent_desc}"
        self._sections.append(("identity", content))
        return self

    def add_runtime_info(self) -> SystemPromptBuilder:
        """添加运行时信息"""
        if not self.config.include_datetime:
            return self

        parts: list[str] = []

        now = datetime.now()
        parts.append(f"Current date and time: {now.strftime('%Y-%m-%d %H:%M:%S')}")

        if self.config.include_timezone:
            parts.append(f"Timezone: {self.config.timezone}")

        if self.config.include_model_info and self.config.model_name:
            parts.append(f"Model: {self.config.model_name}")

        if parts:
            content = "\n".join(parts)
            self._sections.append(("runtime", f"## Runtime Information\n\n{content}"))

        return self

    def add_user_profile(self, content: str) -> SystemPromptBuilder:
        """添加用户画像（全局 USER.md 内容）"""
        if content.strip():
            section = (
                "## 用户画像\n\n"
                "以下是该用户的持久化画像信息，请在整个对话中保持一致的个性化体验：\n\n"
                + content.strip()
            )
            self._sections.append(("user_profile", section))
        return self

    def add_tools(
        self,
        tools: list[AgentTool],
        include_params: bool = False,
    ) -> SystemPromptBuilder:
        """添加工具描述

        Args:
            tools: 工具列表
            include_params: 是否在描述中包含参数信息
        """
        if not self.config.include_tool_descriptions or not tools:
            return self

        tool_descriptions: list[str] = []
        for tool in tools:
            desc = f"- **{tool.name}**: {tool.description}"
            if include_params and tool.parameters:
                params = [f"{p.name}({p.type})" for p in tool.parameters]
                desc += f" [参数: {', '.join(params)}]"
            tool_descriptions.append(desc)

        content = "## Available Tools\n\n" + "\n".join(tool_descriptions)
        content += "\n\nUse these tools when appropriate to help the user."

        self._sections.append(("tools", content))
        return self

    def add_skills(
        self, skills: list[SkillEntry], *, skill_config: SkillConfig | None = None,
    ) -> SystemPromptBuilder:
        """添加技能段落，委托 render_skill_section 决定全文/元数据渲染。"""
        section = render_skill_section(skills, config=skill_config)
        if section:
            self._sections.append(("skills", section))
        return self

    def add_custom_instructions(
        self, instructions: str | None = None
    ) -> SystemPromptBuilder:
        """添加自定义指令"""
        custom = instructions or self.config.custom_instructions
        if custom.strip():
            self._sections.append(("custom", f"## Instructions\n\n{custom}"))
        return self

    def add_context(self, context: dict[str, Any]) -> SystemPromptBuilder:
        """添加上下文信息

        Args:
            context: 上下文字典，可包含用户信息、业务数据等
        """
        if not context:
            return self

        parts: list[str] = []
        for key, value in context.items():
            if isinstance(value, dict):
                # 嵌套字典格式化
                nested = "\n".join(f"  - {k}: {v}" for k, v in value.items())
                parts.append(f"**{key}**:\n{nested}")
            elif isinstance(value, list):
                # 列表格式化
                items = "\n".join(f"  - {item}" for item in value)
                parts.append(f"**{key}**:\n{items}")
            else:
                parts.append(f"**{key}**: {value}")

        if parts:
            content = "## Context\n\n" + "\n\n".join(parts)
            self._sections.append(("context", content))

        return self

    def add_memory_instructions(self) -> SystemPromptBuilder:
        """添加 Memory 使用指令

        当 Agent 配置了 memory_search/memory_get 工具时调用。
        指导 LLM 在回答历史相关问题前先搜索 memory。
        """
        self._sections.append(("memory", MEMORY_INSTRUCTIONS.strip()))
        return self

    def build(self) -> str:
        """构建最终的系统提示"""
        if not self._sections:
            # 默认构建
            self.add_identity()
            self.add_runtime_info()
            if self.config.custom_instructions:
                self.add_custom_instructions()

        parts = [content for _, content in self._sections]
        return "\n\n---\n\n".join(parts)

    @classmethod
    def quick_build(
        cls,
        tools: list[AgentTool] | None = None,
        skills: list[SkillEntry] | None = None,
        context: dict[str, Any] | None = None,
        config: PromptConfig | None = None,
        include_tool_params: bool = False,
        include_memory_instructions: bool = False,
        user_profile_content: str = "",
        skill_config: SkillConfig | None = None,
    ) -> str:
        """快速构建系统提示

        Args:
            tools: 可用工具列表
            skills: 可用技能列表
            context: 上下文信息
            config: 提示配置（含 custom_instructions 等）
            include_tool_params: 是否在工具描述中包含参数信息
            include_memory_instructions: 是否包含 memory 使用指令
            user_profile_content: 全局用户画像 (USER.md) 内容
            skill_config: 技能渲染配置（group 阈值、预算控制等）
        """
        effective_config = config or PromptConfig()
        builder = cls(effective_config)
        builder.add_identity()
        builder.add_runtime_info()

        if user_profile_content:
            builder.add_user_profile(user_profile_content)
        if include_memory_instructions:
            builder.add_memory_instructions()
        if tools:
            builder.add_tools(tools, include_params=include_tool_params)
        if skills:
            builder.add_skills(skills, skill_config=skill_config)
        if context:
            builder.add_context(context)
        if effective_config.thinking_tag_instructions:
            builder.add_section("thinking_tags", effective_config.thinking_tag_instructions)
        builder.add_custom_instructions()
        if include_memory_instructions:
            builder.add_section(
                "memory_reminder",
                "记忆提醒：用户对你回复风格的批评（如「太啰嗦」「太正式」）是偏好表达，必须先调用 memory_write 保存再回复。",
            )

        return builder.build()


# ============ Memory 提示模板 ============

MEMORY_INSTRUCTIONS = """
## 记忆系统

你拥有跨对话的长期记忆能力。通过 memory_search 检索记忆，通过 memory_write 保存记忆。

### 保存规则（最高优先级）

**每轮回复前，必须判断用户消息是否满足以下任一条件；满足则先调用 memory_write，再回复：**
1. 用户表达了偏好或身份（无论直接还是间接）
2. 用户对你的行为提出批评或要求调整——批评 = 偏好的反面表达
3. 用户的表达与上方「用户画像」矛盾

不保存：纯业务查询、寒暄、临时计算

**示例：**
- "好啰嗦，简洁点" → 批评 = 偏好（要简洁）→ memory_write(type=profile)
- "我是张经理，在平安工作" → 身份信息 → memory_write(type=profile)
- "以后贷款渠道都不要" → 持久决策 → memory_write(type=agent_memory)
- "查一下我的保单" → 一次性查询 → 不保存

### 检索（回答前）
在回答关于历史决策、日期、人员、偏好的问题前，先运行 memory_search。
使用 memory_get 获取搜索结果的更多上下文，保持请求量小以节省上下文窗口。

### 格式
内容使用 heading-based markdown：`## 标题\\n内容`
- type=profile 写画像（按标题自动合并，不会重复）
- type=agent_memory 写业务记忆（追加）
"""
