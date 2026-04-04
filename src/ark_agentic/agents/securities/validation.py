"""证券智能体输出校验回调 — 单轮闭环 Cite 幻觉检测

执行流程：
  1. 尝试解析 LLM 结构化输出 {"answer": "...", "citations": [...]}
  2. 以 session.state 中工具快照 + 用户输入作为证据来源
  3. 确定性校验 citations 真实性 + 检测 answer 中未标注的关键元素
  4. 将 answer 字段作为最终 response，校验元数据写入 metadata["validation"]

设计原则：不做 Critic 重试（无二次推理），结果由校验分数与工具证据决定。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ark_agentic.core.callbacks import CallbackContext, CallbackResult
from ark_agentic.core.types import AgentMessage
from ark_agentic.core.validation import (
    CitedResponse,
    EntityTrie,
    parse_cited_response,
    validate_citations,
)

logger = logging.getLogger(__name__)

_FALLBACK_MESSAGE = "抱歉，系统暂时无法核对该回答中的关键数据，请稍后重试或缩小查询范围。"
_HALLUCINATION_DISCLAIMER = "⚠️ 以下回答中部分数据未能通过来源核验，请以实际工具查询结果为准："

# 注入 system prompt 的 cite 格式约束指令（由 agent.py 引用）
CITE_SYSTEM_INSTRUCTION = """\
## 输出格式（强制）

每次回答必须严格使用以下 JSON 格式输出，禁止纯文本回复：

{"answer": "<面向用户的自然语言回答>", "citations": [{"value": "<引用的原始值>", "type": "NUMBER|TIME|ENTITY", "source": "tool_<工具key>或context"}]}

规则：
- answer 中每个数值、时间、实体名称必须在 citations 中有对应条目
- value 使用工具返回或上下文中的原始值，不得改写
- type：NUMBER（数值/金额）、TIME（时间）、ENTITY（股票名/代码）
- source：tool_<工具key>（如 tool_account_overview）或 context（来自用户输入）
- 时间 citations 的 value 必须使用 YYYY-MM-DD 绝对日期格式，不能使用"上个月""上周"等相对描述
- 若用户问"上个月"，则 citation value 填工具实际查询的日期（如 "2026-03-01"）
"""

# securities 工具通过 state_delta 写入 session.state 的 key 列表
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


@dataclass
class SecuritiesValidationConfig:
    """校验回调配置"""

    csv_path: Path
    tool_keys: set[str] = field(default_factory=lambda: _SECURITIES_TOOL_KEYS.copy())
    fallback_message: str = _FALLBACK_MESSAGE
    hallucination_disclaimer: str = _HALLUCINATION_DISCLAIMER


def _build_tool_sources(
    state: dict[str, Any],
    tool_keys: set[str],
) -> dict[str, str]:
    """从 session.state 中提取工具数据，转为 {tool_key: text} 供 citation 校验。"""
    sources: dict[str, str] = {}
    for key in tool_keys:
        data = state.get(key)
        if data is None:
            continue
        if isinstance(data, (dict, list)):
            sources[key] = json.dumps(data, ensure_ascii=False)
        else:
            sources[key] = str(data)
    return sources


def create_securities_validation_callback(
    *,
    csv_path: Path,
    llm: Any | None = None,  # 保留参数兼容性，新设计无 Critic 重试
    config: SecuritiesValidationConfig | None = None,
):
    """创建证券智能体的 Cite 幻觉检测回调。

    Args:
        csv_path: A 股白名单 CSV 文件路径（列: code, name, exchange）
        llm:      已弃用，保留仅为接口兼容，传入不报错但不会使用
        config:   校验配置
    """
    if config is None:
        config = SecuritiesValidationConfig(csv_path=csv_path)

    trie = EntityTrie()
    trie.load_from_csv(config.csv_path)

    async def _validation_callback(
        ctx: CallbackContext, *, response: AgentMessage
    ) -> CallbackResult | None:
        content = response.content
        if not content:
            return None

        # Step1：尝试解析结构化输出；纯文本回退为空 citations
        cited = parse_cited_response(content)
        is_structured = cited is not None
        if cited is None:
            cited = CitedResponse(answer=content, citations=[])

        # Step2：从 session.state 构建工具证据来源
        tool_sources = _build_tool_sources(ctx.session.state, config.tool_keys)
        if not tool_sources:
            response.metadata["validation"] = {
                "route": "skip",
                "reason": "no_tool_data",
                "structured": is_structured,
            }
            return None

        # Step3：确定性校验
        result = validate_citations(
            cited,
            tool_sources,
            context=ctx.user_input,
            entity_trie=trie,
        )

        # Step4：写入校验元数据
        response.metadata["validation"] = {
            "route": result.route,
            "score": result.score,
            "passed": result.passed,
            "structured": is_structured,
            "errors": [
                {"type": e.type, "value": e.value, "source": e.source}
                for e in result.errors
            ],
        }

        if result.route == "retry":
            logger.warning(
                "[VALIDATION] cite check failed: score=%.2f errors=%d structured=%s",
                result.score,
                len(result.errors),
                is_structured,
            )

        # Step5：输出最终 response
        if is_structured:
            # 结构化输出：提取 answer；幻觉时在 answer 前插入免责声明
            if result.route == "retry":
                final_content = f"{config.hallucination_disclaimer}\n\n{cited.answer}"
            else:
                final_content = cited.answer
            new_response = AgentMessage.assistant(content=final_content)
            new_response.metadata.update(response.metadata)
            return CallbackResult(response=new_response)

        if result.route == "retry":
            # 纯文本 + 幻觉：数据来源无法核验，直接兜底
            fallback = AgentMessage.assistant(content=config.fallback_message)
            fallback.metadata.update(response.metadata)
            return CallbackResult(response=fallback)

        return None

    return _validation_callback
