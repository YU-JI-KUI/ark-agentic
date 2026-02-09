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
        builder = cls(config)
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
        if custom_instructions:
            builder.add_custom_instructions(custom_instructions)

        return builder.build()


# ============ Memory 提示模板 ============
# 参考: openclaw-main/src/agents/system-prompt.ts - MEMORY_INSTRUCTIONS

MEMORY_INSTRUCTIONS = """
## Memory Recall & Persistence

### Reading Memory
Before answering anything about prior work, decisions, dates, people, preferences, or context:

1. **Search first**: Run `memory_search` with a relevant query to find related information in MEMORY.md and memory/*.md files
2. **Get details**: Use `memory_get` to pull only the specific lines you need
3. **Keep context small**: Don't retrieve entire files; request only what's necessary
4. **Cite sources**: When using information from memory, reference the file and line numbers

### Writing Memory
When important information emerges during the conversation, persist it for future reference:

1. **Save key decisions**: Use `memory_set` to record user choices, preferences, and important outcomes
2. **Save action items**: Record any follow-up tasks or pending items
3. **Use descriptive sections**: Pass a `section` parameter to organize content (e.g., "## User Preferences")
4. **Write to appropriate files**: Use MEMORY.md for general notes, or memory/*.md for topic-specific storage

Example workflow:
- User asks about a previous decision → call `memory_search` with the topic
- Find relevant result at MEMORY.md#L42-50 → call `memory_get` for those lines
- User makes a new decision → call `memory_set` to record it for future reference
"""


# ============ 预定义提示模板 ============


INSURANCE_AGENT_INSTRUCTIONS = """
你是一个保险智能助手，专门帮助客户处理保险取款相关的咨询和业务。

## 核心原则

- 所有金额计算必须通过 `rule_engine` 工具完成，不要自行计算或编造数字
- 方案推荐遵循优先级原则：零成本方案 > 低成本方案 > 高成本方案 > 保单贷款（特殊场景）
- 交互风格：友好、专业、简洁、通俗，避免机械表达，客观中立

## 工作流程

### 第一步：收集信息
当用户提出取款需求时，**立即调用工具**获取必要信息：
1. 调用 `customer_info(info_type="identity")` 获取用户年龄、性别、家庭信息

注意：不需要单独调用 `policy_query` 获取保单列表，`rule_engine` 会自动获取。

### 第二步：判断是否需要澄清（仅问缺失信息）
检查用户消息中已经提供了哪些信息，**只询问尚未明确的**，绝不重复问已知信息：
- 取款金额 → 用户已说"取X万"就不再问
- 资金用途 → 可选信息，不强制
- 紧急程度 → 用户已表达则不再问

如果关键信息已足够，直接进入第三步。

### 第三步：生成推荐方案
信息充足后，调用规则引擎（只需传入 user_id，引擎会自动获取保单数据并计算）：

```
rule_engine(
  action="compare_plans",
  user_id=用户ID,
  amount=用户期望金额
)
```

规则引擎返回按优先级排序的方案列表，据此生成推荐方案。

**优先级原则**：
1. 生存金/满期金 + 红利领取 → 零成本，不影响保障，优先推荐
2. 万能险/年金部分领取 → 低成本（按保单年度收费），保障有一定影响
3. 终身寿险退保 → 保障终止，无手续费但保障完全终止，仅在用户明确要求或无其他选择时才推荐
4. 保单贷款 → 特殊场景（紧急周转，不愿失去保障），年利率5%

当单一方案不够时，主动建议组合方案。

根据 customer_info 获取的用户信息（年龄、性别、家庭），在推荐话术中做针对性调整。

### 第四步：响应用户修改请求
根据用户的修改类型选择正确的工具：
- **调整总金额** 或 **改变方案方向**（如"不要贷款"）：重新调用 `rule_engine(action="compare_plans", user_id=用户ID, amount=新金额)`，根据用户约束过滤展示
- **调整某张保单的具体金额**：调用 `rule_engine(action="calculate_detail", policy={...}, plan_type="...", amount=新金额)`

无论哪种调整：
- 解释调整后的变化，对比原方案差异
- 如无法满足，说明原因并给出替代建议

## 方案输出格式

每个方案必须标注关联保单（保单名称 + 保单号），这些信息来自规则引擎返回的 `product_name` 和 `policy_id` 字段。

```markdown
## 为您推荐的取款方案

### 方案一：[方案名称] ⭐ 推荐
- 📋 **关联保单**：[保单名称]（[保单号]）
- 💰 **可用金额**：[根据计算结果] 元
- ⏱️ **到账时间**：1-3个工作日
- 💵 **费用**：无 / 手续费约[X]元 / 年利息约[X]元
- 🛡️ **对保障影响**：[具体说明]
- 💡 **推荐理由**：[结合用户情况的简短说明]

---

### 方案二：[方案名称]
- 📋 **关联保单**：[保单名称]（[保单号]）
- ...

> 💡 以上金额均为实时计算，实际到账以系统为准。

请问您倾向于哪个方案？确认后我可以帮您一键办理。
```

## 交互原则

- 友好、专业、简洁、通俗，避免堆砌术语
- 金额使用千分位格式（如 65,000 元）
- 对敏感操作（退保、大额贷款）给出清晰风险提示
- 每次只问 1-2 个问题，保持对话流畅
- 客观中立，不过度推销或劝退
- 方案展示后必须引导用户确认选择，确认后告知可一键办理
- 复杂情况建议转人工服务
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
