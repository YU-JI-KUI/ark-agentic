"""证券智能体校验辅助配置

提供 VALIDATION_SYSTEM_INSTRUCTION（注入 system prompt，约束回答仅基于工具与上下文）。

事实校验由 core 框架完成：Runner 累积本轮工具返回至 ``temp:grounding_tool_outputs_by_name``，
create_citation_validation_hook 在 before_loop_end 做后置 grounding（无需枚举业务 state key）。
"""

from __future__ import annotations

# 注入 system prompt 的轻量校验约束（由 agent.py 引用）
VALIDATION_SYSTEM_INSTRUCTION = """\
## 回答约束

请仅依据当前轮工具返回结果和已有上下文作答。

要求：
- 不要编造证券名称、证券代码、数值、日期、收益或持仓信息
- 当工具结果中没有足够依据时，请明确说明暂时无法确认
- 优先直接复用工具返回中的原始事实表达，避免自行改写关键数据
"""
