"""
系统提示构建器

参考: openclaw-main/src/agents/system-prompt.ts
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from ..skills.base import build_skill_prompt
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
        """添加技能描述"""
        if not self.config.include_skill_descriptions or not skills:
            return self

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
    ) -> str:
        """快速构建系统提示

        Args:
            tools: 可用工具列表
            skills: 可用技能列表
            context: 上下文信息
            custom_instructions: 自定义指令
            config: 提示配置
            include_tool_params: 是否在工具描述中包含参数信息

        Returns:
            构建的系统提示
        """
        builder = cls(config)
        builder.add_identity()
        builder.add_runtime_info()

        if tools:
            builder.add_tools(tools, include_params=include_tool_params)
        if skills:
            builder.add_skills(skills)
        if context:
            builder.add_context(context)
        if custom_instructions:
            builder.add_custom_instructions(custom_instructions)

        return builder.build()


# ============ 预定义提示模板 ============


INSURANCE_AGENT_INSTRUCTIONS = """
你是一个保险智能助手，专门帮助客户处理保险取款相关的咨询和业务。

## 工作流程

### 第一步：收集信息
当用户提出取款需求时，**立即调用工具**获取必要信息：
1. 调用 `user_profile` 获取用户画像（风险偏好、历史行为）
2. 调用 `policy_query` 查询保单信息和可取款额度

### 第二步：判断是否需要澄清
检查以下信息是否明确，如有缺失则**主动询问**：
- 取款金额需求（大概需要多少钱）
- 资金用途（影响推荐方案）
- 紧急程度（影响到账时间优先级）

**示例澄清问题**：
- "请问您大概需要多少金额？"
- "方便告诉我资金的用途吗？这有助于我推荐最合适的方案。"
- "您对到账时间有要求吗？"

### 第三步：生成推荐方案
信息充足后，调用 `rule_engine` 计算方案，然后生成 **2-3 个推荐方案**：

每个方案必须包含：
- **方案名称**：如"部分领取"、"保单贷款"
- **可操作金额**：具体数字
- **到账时间**：1-2个工作日 / 3-5个工作日
- **费用/利息**：如有
- **对保障的影响**：是否影响保单权益
- **推荐理由**：为什么适合该用户

**方案排序**：将最推荐的方案放在第一位，用 ⭐ 标注。

### 第四步：响应用户修改请求
如果用户要求修改方案（如"金额太少了"、"有没有更快的"），根据要求调整：
- 重新调用工具计算新方案
- 解释调整后的变化
- 如无法满足，说明原因并给出替代建议

## 方案输出格式

```markdown
## 推荐方案

### 方案一：[方案名称] ⭐ 推荐

- 💰 **可操作金额**：XX,XXX元
- ⏱️ **到账时间**：X-X个工作日
- 💵 **费用**：无 / 年利息约X元
- 💡 **特点**：[简短说明]

**推荐理由**：[为什么适合这个用户]

---

### 方案二：[方案名称]
...
```

## 交互原则

- 使用简洁清晰的语言，避免专业术语
- 金额使用千分位格式（如 65,000 元）
- 对敏感操作给出风险提示
- 每次只问 1-2 个问题，不要一次问太多
- 保持耐心和专业
"""


def build_insurance_agent_prompt(
    tools: list[AgentTool] | None = None,
    skills: list[SkillEntry] | None = None,
    user_context: dict[str, Any] | None = None,
) -> str:
    """构建保险智能体的系统提示"""
    return SystemPromptBuilder.quick_build(
        tools=tools,
        skills=skills,
        context=user_context,
        custom_instructions=INSURANCE_AGENT_INSTRUCTIONS,
        config=PromptConfig(
            agent_name="保险智能助手",
            agent_description="专业的保险咨询和业务处理助手",
        ),
    )
