"""
系统提示构建器

参考: openclaw-main/src/agents/system-prompt.ts
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ..memory.rules import MEMORY_FILTER_RULES
from ..skills.base import (
    LOAD_ONE_SKILL_INSTRUCTIONS,
    SkillConfig,
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

    # 全局协议（identity/runtime 之后注入）
    system_protocol: str = ""

    # 自定义指令
    custom_instructions: str = ""

    # 工具描述
    include_tool_descriptions: bool = False

    # <think>/<final> 标签指引（非空时注入到 system prompt）
    thinking_tag_instructions: str = ""


_UNWRAPPED_SECTIONS = frozenset({"identity"})

MEMORY_WRITE_PROTOCOL = """\
⚠️ 必须执行：你拥有 memory_write 工具，用于自动保存用户长期偏好。
每次回复前扫描用户消息，若包含可记录内容，必须先调用 memory_write 再回复，即使用户没有明确说"记住"。

## 记录规则（mandatory）
{filter_rules}

## 增量写入格式
memory_write 只写变化的标题，其他自动保留。
- 新增/修改：`## 标题\\n内容`（同名覆盖）
- 删除：`## 标题\\n`（空内容移除）
标题规范：简短通用（如 ## 身份信息、## 回复风格、## 业务偏好、## 风险偏好），优先复用已有标题。""".format(filter_rules=MEMORY_FILTER_RULES)



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

        content = f"你是{agent_name}. {agent_desc}"
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
            self._sections.append(("runtime", content))

        return self

    def add_memory_instructions(self) -> SystemPromptBuilder:
        """添加 memory 写入协议（always-on，无需 profile 数据）"""
        self._sections.append(("auto_memory_instructions", MEMORY_WRITE_PROTOCOL))
        return self

    def add_user_profile(self, content: str) -> SystemPromptBuilder:
        """添加用户画像（MEMORY.md 内容），仅含读取/应用规则 + 数据"""
        if content.strip():
            section = (
                "以下是该用户的持久化偏好，每次回复和工具调用时主动遵守：\n"
                "- 调用工具前，检查是否有相关偏好约束，据此过滤参数或排除选项\n"
                "- 展示结果时，排除用户已明确拒绝的类型\n"
                "- 措辞匹配用户的风格偏好\n\n"
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

        content = "\n".join(tool_descriptions)
        content += "\n\nUse these tools when appropriate to help the user."

        self._sections.append(("tools", content))
        return self

    def add_skills(
        self, skills: list[SkillEntry], *, skill_config: SkillConfig | None = None,
    ) -> SystemPromptBuilder:
        """添加技能段落。

        full 模式: 全文注入到 <skills> 段。
        dynamic 模式: 行为指令和元数据分离 —— 指令进 <skill_loading_protocol>，
                      元数据进 <available_skills>，避免行为指令被名词标签淹没。
        """
        if not skills:
            return self
        sc = skill_config or SkillConfig()
        from ..types import SkillLoadMode

        if sc.load_mode == SkillLoadMode.full:
            section = build_skill_prompt(skills)
            if section:
                self._sections.append(("skills", section))
        else:
            metadata = format_skills_metadata_for_prompt(skills, config=sc)
            if metadata:
                self._sections.append(
                    ("skill_loading_protocol", LOAD_ONE_SKILL_INSTRUCTIONS.strip())
                )
                self._sections.append(("available_skills", metadata))
        return self

    def add_custom_instructions(
        self, instructions: str | None = None
    ) -> SystemPromptBuilder:
        """添加自定义指令"""
        custom = instructions or self.config.custom_instructions
        if custom.strip():
            self._sections.append(("instructions", custom))
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
            content = "\n\n".join(parts)
            self._sections.append(("context", content))

        return self

    def build(self) -> str:
        """构建最终的系统提示"""
        if not self._sections:
            self.add_identity()
            self.add_runtime_info()
            if self.config.custom_instructions:
                self.add_custom_instructions()

        parts: list[str] = []
        for name, content in self._sections:
            if name in _UNWRAPPED_SECTIONS:
                parts.append(content)
            else:
                parts.append(f"<{name}>\n{content}\n</{name}>")
        return "\n\n".join(parts)

    @classmethod
    def quick_build(
        cls,
        tools: list[AgentTool] | None = None,
        skills: list[SkillEntry] | None = None,
        context: dict[str, Any] | None = None,
        config: PromptConfig | None = None,
        include_tool_params: bool = False,
        user_profile_content: str = "",
        skill_config: SkillConfig | None = None,
        enable_memory: bool = False,
    ) -> str:
        """快速构建系统提示

        Args:
            tools: 可用工具列表
            skills: 可用技能列表
            context: 上下文信息
            config: 提示配置（含 custom_instructions 等）
            include_tool_params: 是否在工具描述中包含参数信息
            user_profile_content: 全局用户画像 (USER.md) 内容
            skill_config: 技能渲染配置（group 阈值、预算控制等）
            enable_memory: 是否注入 memory 写入协议（仅当 memory 系统启用时为 True）
        """
        effective_config = config or PromptConfig()
        builder = cls(effective_config)
        builder.add_identity()
        builder.add_runtime_info()

        if effective_config.system_protocol:
            builder.add_section("system_protocol", effective_config.system_protocol)

        if tools:
            builder.add_tools(tools, include_params=include_tool_params)
        if skills:
            builder.add_skills(skills, skill_config=skill_config)
        if context:
            builder.add_context(context)
        if effective_config.thinking_tag_instructions:
            builder.add_section("thinking_tags", effective_config.thinking_tag_instructions)
        if user_profile_content:
            builder.add_user_profile(user_profile_content)
        if enable_memory:
            builder.add_memory_instructions()
        builder.add_custom_instructions()

        return builder.build()


