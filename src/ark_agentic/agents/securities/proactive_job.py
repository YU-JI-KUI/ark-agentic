"""SecuritiesProactiveJob — 证券资产管理 Agent 的主动服务 Job

职责：
  - 定时扫描用户 memory，识别股票/基金价格关注意图
  - 调用 security_info_search 工具获取最新行情数据
  - 生成主动推送通知（如"平安银行今日涨 2.3%，当前价 11.45 元"）

子类只需覆盖三个钩子：
  - intent_keywords    : 证券领域关键词（无 LLM，<1ms 快速过滤）
  - get_intent_prompt  : 告诉 LLM 识别哪些证券意图
  - fetch_data         : 调用 security_info_search 获取实时数据
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ark_agentic.plugins.jobs.proactive_service import ProactiveServiceJob
from ark_agentic.core.types import ToolCall

if TYPE_CHECKING:
    pass

# ── 意图提取 Prompt 模板 ──────────────────────────────────────────────────────
_INTENT_PROMPT_TEMPLATE = """\
今天是 {today}。

请分析以下用户记忆，判断用户是否对某只股票或基金有持续关注意图（如价格提醒、持仓跟踪、目标价提醒等）。

用户记忆：
{memory}

请以 JSON 格式返回，格式如下：
{{
  "intents": [
    {{
      "type": "stock_alert",
      "title": "股票行情播报",
      "symbol": "股票代码或名称",
      "description": "用户的具体关注点描述"
    }}
  ]
}}

要求：
- 只返回有实际查询价值的意图（用户明确表示关注、持有、或设定目标价）
- 若无相关意图，返回 {{"intents": []}}
- 每条意图的 symbol 填写用户提到的股票/基金名称或代码
- type 可以是 stock_alert（股票）或 fund_alert（基金）
- 只返回 JSON，不要额外解释
"""


class SecuritiesProactiveJob(ProactiveServiceJob):
    """证券资产管理 Agent 的主动服务 Job。

    每天定时扫描所有证券用户的 memory，找出有股票/基金关注意图的用户，
    调用 security_info_search 工具查询实时行情，主动推送通知。

    使用示例（在 create_securities_agent 中）：
        runner = AgentRunner(...)
        runner.set_proactive_job_class(SecuritiesProactiveJob)
    """

    # ── 关键词快速过滤（无 LLM，<1ms，覆盖率高比精确率更重要）────────────────
    intent_keywords = [
        "股票", "股价", "涨到", "跌到", "目标价",
        "关注", "持仓", "基金", "净值", "持有",
        "提醒", "通知我", "盯着", "到价",
    ]

    # ── Hook 1：意图提取 Prompt ──────────────────────────────────────────────

    def get_intent_prompt(self, memory: str, today: str) -> str:
        return _INTENT_PROMPT_TEMPLATE.format(memory=memory, today=today)

    # ── Hook 2：调用工具获取实时数据 ─────────────────────────────────────────

    async def fetch_data(self, intent: dict[str, Any], user_id: str) -> str:
        """调用 security_info_search 工具查询股票/基金实时数据。"""
        symbol = intent.get("symbol", "")
        if not symbol:
            return "未识别到有效的股票或基金代码"

        tool = self._tool_registry.get("security_info_search")
        if tool is None:
            return f"工具 security_info_search 不可用，无法查询 {symbol}"

        tool_call = ToolCall(
            id="proactive_query",
            name="security_info_search",
            arguments={"query": symbol, "include_dividend": False},
        )

        try:
            result = await tool.execute(tool_call, context=None)
            if result.is_error:
                return f"查询 {symbol} 时发生错误：{result.error}"

            # 将工具返回的结构化数据转为可读文字摘要
            return self._format_stock_result(symbol, result.data)
        except Exception as e:
            return f"查询 {symbol} 失败：{e}"

    # ── 内部辅助：格式化股票查询结果为可读文本 ───────────────────────────────

    def _format_stock_result(self, query: str, data: Any) -> str:
        """将 security_info_search 返回的 dict 转换为简洁可读的文字摘要。"""
        if not data or not isinstance(data, dict):
            return f"未找到与 {query} 相关的股票信息"

        # 处理模糊匹配返回多个候选的情况
        candidates = data.get("candidates")
        if candidates and isinstance(candidates, list):
            if len(candidates) == 0:
                return f"未找到与 {query} 相关的股票"
            if len(candidates) == 1:
                data = candidates[0]
            else:
                names = "、".join(
                    c.get("name", c.get("code", "?")) for c in candidates[:3]
                )
                return f"查询 {query} 找到多只匹配股票：{names}，请用户指定具体股票"

        # 提取核心字段
        name = data.get("name", query)
        code = data.get("full_code") or data.get("code", "")
        exchange = data.get("exchange", "")

        parts = [f"股票：{name}（{code}）"]
        if exchange:
            parts.append(f"交易所：{exchange}")

        # 分红信息（如果有）
        dividend = data.get("dividend")
        if dividend and isinstance(dividend, dict):
            dividend_per_share = dividend.get("dividend_per_share")
            dividend_yield = dividend.get("dividend_yield")
            if dividend_per_share:
                parts.append(f"每股分红：{dividend_per_share} 元")
            if dividend_yield:
                parts.append(f"股息率：{dividend_yield}")

        return "；".join(parts)
