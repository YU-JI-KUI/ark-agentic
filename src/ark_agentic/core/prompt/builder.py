"""
系统提示构建器

参考: openclaw-main/src/agents/system-prompt.ts
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ..skills.base import (
    build_skill_prompt,
    format_skills_metadata_for_prompt,
)
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

    # 技能描述
    include_skill_descriptions: bool = True

    # 仅注入技能元数据（不注入全文）；模型通过 read_skill 按 id 加载一个技能
    use_skill_metadata_only: bool = False

    # <think>/<final> 标签指引（非空时注入到 system prompt）
    thinking_tag_instructions: str = ""


# 动态模式下的 skill 加载说明（对齐 openclaw buildSkillsSection）
LOAD_ONE_SKILL_INSTRUCTIONS = """\
## 技能（业务必选协议）
在回复任何业务相关问题之前，你必须执行以下步骤：
1. 扫描 <available_skills>，根据 <description> 识别匹配的技能。
2. 如果某个技能匹配（即使只是部分匹配）：调用 `read_skill` 并传入对应 <id>，然后严格按照返回的指令执行。
3. 如果多个技能可能适用：选择最具体的那个，调用 `read_skill`。
4. 仅当用户的问题与所有已列技能完全无关时（如日常寒暄、通用知识问题），才可直接回复而不加载技能。
重要：业务类问题必须通过技能处理，禁止用通用回答替代技能流程。
约束：每轮最多读取一个技能；必须先选定再读取。"""


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

    def add_skills(self, skills: list[SkillEntry]) -> SystemPromptBuilder:
        """添加技能描述（全文或仅元数据 + 加载说明）。"""
        if not self.config.include_skill_descriptions or not skills:
            return self

        if self.config.use_skill_metadata_only:
            skill_prompt = format_skills_metadata_for_prompt(skills)
            if skill_prompt:
                # 强制指令在前，XML 元数据在后（对齐 openclaw buildSkillsSection）
                combined = LOAD_ONE_SKILL_INSTRUCTIONS.strip() + "\n\n" + skill_prompt
                self._sections.append(("skills", combined))
        else:
            skill_prompt = build_skill_prompt(skills)
            if skill_prompt:
                self._sections.append(("skills", skill_prompt))

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
        custom_instructions: str | None = None,
        config: PromptConfig | None = None,
        include_tool_params: bool = False,
        include_memory_instructions: bool = False,
    ) -> str:
        """快速构建系统提示

        Args:
            tools: 可用工具列表
            skills: 可用技能列表
            context: 上下文信息
            custom_instructions: 自定义指令
            config: 提示配置
            include_tool_params: 是否在工具描述中包含参数信息
            include_memory_instructions: 是否包含 memory 使用指令

        Returns:
            构建的系统提示
        """
        effective_config = config or PromptConfig()
        builder = cls(effective_config)
        builder.add_identity()
        builder.add_runtime_info()

        if tools:
            builder.add_tools(tools, include_params=include_tool_params)
        if include_memory_instructions:
            builder.add_memory_instructions()
        if skills:
            builder.add_skills(skills)
        if context:
            builder.add_context(context)
        if effective_config.thinking_tag_instructions:
            builder.add_section("thinking_tags", effective_config.thinking_tag_instructions)
        if custom_instructions:
            builder.add_custom_instructions(custom_instructions)

        return builder.build()


# ============ Memory 提示模板 ============
# 参考: openclaw-main/src/agents/system-prompt.ts - MEMORY_INSTRUCTIONS

MEMORY_INSTRUCTIONS = """
## 记忆检索与持久化

### 读取记忆
在回答任何关于先前工作、决策、日期、人员、偏好或上下文的问题之前：

1. **先搜索**：使用相关查询运行 `memory_search`，在 MEMORY.md 和 memory/*.md 文件中查找相关信息
2. **获取详情**：使用 `memory_get` 仅提取你需要的特定行
3. **保持上下文精简**：不要检索整个文件；只请求必要的内容
4. **引用来源**：使用记忆中的信息时，引用文件和行号

### 写入记忆
当对话中出现重要信息时，将其持久化以供未来参考：

1. **保存关键决策**：使用 `memory_set` 记录用户选择、偏好和重要结果
2. **保存行动项**：记录任何后续任务或待办事项
3. **使用描述性章节**：传递 `section` 参数来组织内容（例如，"## 用户偏好"）
4. **写入适当的文件**：使用 MEMORY.md 存储一般笔记，或使用 memory/*.md 存储特定主题

示例工作流：
- 用户询问之前的决策 → 使用主题调用 `memory_search`
- 在 MEMORY.md#L42-50 找到相关结果 → 调用 `memory_get` 获取这些行
- 用户做出新决策 → 调用 `memory_set` 记录以供未来参考
"""
