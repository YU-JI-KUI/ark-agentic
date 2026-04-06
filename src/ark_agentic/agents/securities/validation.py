"""证券智能体 Citation 辅助配置

职责：
  1. 定义 _SECURITIES_TOOL_KEYS（证券业务工具写入 session.state 的 key 集合）
  2. 提供 CITE_SYSTEM_INSTRUCTION（注入 system prompt，指导模型先调用 record_citations）

校验逻辑与工具实现均位于 core 框架：
  - core.tools.citations.RecordCitationsTool  （citation 记录工具）
  - core.validation.create_citation_validation_hook  （before_complete 校验 hook）
"""

from __future__ import annotations

# 证券工具通过 state_delta 写入 session.state 的 key 列表
_SECURITIES_TOOL_KEYS: set[str] = {
    "account_overview",
    "cash_assets",
    "etf_holdings",
    "hksc_holdings",
    "fund_holdings",
    "security_detail",
    "branch_info",
    "security_info_search",
    "stock_profit_ranking",
    "asset_profit_hist_period",
    "asset_profit_hist_range",
    "stock_daily_profit_range",
    "stock_daily_profit_month",
}

# 注入 system prompt 的 citation 约束指令（由 agent.py 引用）
CITE_SYSTEM_INSTRUCTION = """\
## 引用校验（强制）

在输出最终自然语言回答之前，**必须先调用 `record_citations` 工具**，记录本次回答中所有关键数据的引用来源。

工具返回成功后，直接输出您的自然语言回答（无需再次传入答案文本）。
系统会在您的回答落地前自动进行校验：
- 校验通过：回答正常发布
- 校验失败：系统反馈具体错误，您需要重新调用 `record_citations` 并修正回答

citations 填写规则：
- 回答中每个数值、时间、实体名称必须有对应 citation 条目
- value 使用工具返回或上下文中的原始值，不得改写
- type：NUMBER（数值/金额/百分比）、TIME（时间）、ENTITY（股票名/代码）
- source：tool_<工具key>（如 tool_account_overview）或 context（来自用户输入）
- 时间 citation 的 value 必须使用 YYYY-MM-DD 绝对日期格式，不得使用"上个月"等相对表述
"""
