"""
Securities preset card extractors.

Each extractor reads data from ``context`` (populated via ``state_delta``),
enriches with account info (masked) and titles, then calls
``TemplateRenderer`` to produce the frontend-ready payload.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from ark_agentic.core.a2ui.blocks import A2UIOutput
from ark_agentic.core.a2ui.preset_registry import PresetRegistry

from ..template_renderer import TemplateRenderer


# ---------------------------------------------------------------------------
# Helpers (migrated from display_card.py)
# ---------------------------------------------------------------------------

def _get_context_value(
    context: dict[str, Any] | None, key: str, default: Any = None
) -> Any:
    """从 context 获取值，优先 user: 前缀，兼容裸 key"""
    if context is None:
        return default
    prefixed = f"user:{key}"
    if prefixed in context:
        return context[prefixed]
    if key in context:
        return context[key]
    return default


def _mask_account(account: str | None) -> str:
    """脱敏账号：保留前3位和后4位，中间替换为 ****"""
    if not account:
        return "****"
    if len(account) <= 7:
        return account[:3] + "****"
    return account[:3] + "****" + account[-4:]


def _read_source_data(
    context: dict[str, Any], source_tool: str
) -> dict[str, Any]:
    """Read and parse the upstream data tool result from context."""
    source_data = context.get(source_tool) or {}

    if isinstance(source_data, str):
        try:
            source_data = json.loads(source_data)
        except json.JSONDecodeError:
            return {}

    return source_data if isinstance(source_data, dict) else {}


def _enrich_common(
    context: dict[str, Any],
    data: dict[str, Any],
    title_template: str,
) -> tuple[dict[str, Any], str]:
    """Inject masked account title and account_type into data dict."""
    masked = _mask_account(_get_context_value(context, "account"))
    account_type = _get_context_value(context, "account_type", "normal")
    data["title"] = title_template.format(masked=masked)
    data["account_type"] = account_type
    return data, account_type


# ---------------------------------------------------------------------------
# Individual extractors (CardExtractor protocol)
# ---------------------------------------------------------------------------

_ASSET_CLASS_MAP: dict[str, Literal["ETF", "HKSC", "Fund"]] = {
    "etf_holdings": "ETF",
    "hksc_holdings": "HKSC",
    "fund_holdings": "Fund",
}

_HOLDINGS_TITLE: dict[str, str] = {
    "etf_holdings": "资金账号：{masked}的ETF资产信息",
    "hksc_holdings": "资金账号：{masked}的港股通资产信息",
    "fund_holdings": "资金账号：{masked}的基金资产信息",
}


def _make_holdings_extractor(source_tool: str):
    """Factory for holdings_list extractors (ETF / HKSC / Fund)."""
    asset_class = _ASSET_CLASS_MAP[source_tool]
    title_tpl = _HOLDINGS_TITLE[source_tool]

    def extractor(context: dict[str, Any], card_args: dict[str, Any] | None) -> A2UIOutput:
        data = _read_source_data(context, source_tool)
        if not data:
            return A2UIOutput(template_data={"error": f"未找到 {source_tool} 数据"})
        if data.get("_error") == "margin_not_supported":
            return A2UIOutput(
                template_data={
                    "template_id": source_tool,
                    "account_type": data.get("account_type", "margin"),
                }
            )
        _enrich_common(context, data, title_tpl)
        return A2UIOutput(
            template_data=TemplateRenderer.render_holdings_list_card(asset_class, data),
        )

    return extractor


def _account_overview_extractor(
    context: dict[str, Any], card_args: dict[str, Any] | None
) -> A2UIOutput:
    data = _read_source_data(context, "account_overview")
    if not data:
        return A2UIOutput(template_data={"error": "未找到 account_overview 数据"})
    _enrich_common(context, data, "资金账号：{masked}的资产信息")
    return A2UIOutput(
        template_data=TemplateRenderer.render_account_overview_card(data),
    )


def _cash_assets_extractor(
    context: dict[str, Any], card_args: dict[str, Any] | None
) -> A2UIOutput:
    data = _read_source_data(context, "cash_assets")
    if not data:
        return A2UIOutput(template_data={"error": "未找到 cash_assets 数据"})
    _enrich_common(context, data, "资金账号：{masked}的现金资产信息")
    return A2UIOutput(
        template_data=TemplateRenderer.render_cash_assets_card(data),
    )


def _security_detail_extractor(
    context: dict[str, Any], card_args: dict[str, Any] | None
) -> A2UIOutput:
    data = _read_source_data(context, "security_detail")
    if not data:
        return A2UIOutput(template_data={"error": "未找到 security_detail 数据"})
    account_type = _get_context_value(context, "account_type", "normal")
    data["account_type"] = account_type
    return A2UIOutput(
        template_data=TemplateRenderer.render_security_detail_card(data),
    )


def _branch_info_extractor(
    context: dict[str, Any], card_args: dict[str, Any] | None
) -> A2UIOutput:
    data = _read_source_data(context, "branch_info")
    if not data:
        return A2UIOutput(template_data={"error": "未找到 branch_info 数据"})
    _enrich_common(context, data, "资金账号：{masked}的开户营业部信息")
    return A2UIOutput(
        template_data=TemplateRenderer.render_branch_info_card(data),
    )


def _make_asset_profit_hist_extractor(source_tool: str):
    """Factory for asset_profit_hist extractors (period / range)."""
    def extractor(context: dict[str, Any], card_args: dict[str, Any] | None) -> A2UIOutput:
        data = _read_source_data(context, source_tool)
        if not data:
            return A2UIOutput(template_data={"error": f"未找到 {source_tool} 数据"})
        _enrich_common(context, data, "资金账号：{masked}的资产历史收益曲线")
        return A2UIOutput(
            template_data=TemplateRenderer.render_asset_profit_hist_card(data),
        )
    return extractor


def _stock_profit_ranking_extractor(
    context: dict[str, Any], card_args: dict[str, Any] | None
) -> A2UIOutput:
    data = _read_source_data(context, "stock_profit_ranking")
    if not data:
        return A2UIOutput(template_data={"error": "未找到 stock_profit_ranking 数据"})
    masked = _mask_account(_get_context_value(context, "account"))
    data["title"] = f"资金账号：{masked}的股票盈亏排行"
    return A2UIOutput(
        template_data=TemplateRenderer.render_stock_profit_ranking_card(data),
    )


def _make_stock_daily_profit_extractor(source_tool: str):
    """Factory for stock_daily_profit extractors (range / month)."""
    def extractor(context: dict[str, Any], card_args: dict[str, Any] | None) -> A2UIOutput:
        data = _read_source_data(context, source_tool)
        if not data:
            return A2UIOutput(template_data={"error": f"未找到 {source_tool} 数据"})
        _enrich_common(context, data, "资金账号：{masked}的股票每日收益")
        return A2UIOutput(
            template_data=TemplateRenderer.render_stock_daily_profit_calendar_card(data),
        )
    return extractor


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

SECURITIES_PRESETS = PresetRegistry()

SECURITIES_PRESETS.register("etf_holdings", _make_holdings_extractor("etf_holdings"))
SECURITIES_PRESETS.register("hksc_holdings", _make_holdings_extractor("hksc_holdings"))
SECURITIES_PRESETS.register("fund_holdings", _make_holdings_extractor("fund_holdings"))
SECURITIES_PRESETS.register("account_overview", _account_overview_extractor)
SECURITIES_PRESETS.register("cash_assets", _cash_assets_extractor)
SECURITIES_PRESETS.register("security_detail", _security_detail_extractor)
SECURITIES_PRESETS.register("branch_info", _branch_info_extractor)
SECURITIES_PRESETS.register("asset_profit_hist_period", _make_asset_profit_hist_extractor("asset_profit_hist_period"))
SECURITIES_PRESETS.register("asset_profit_hist_range", _make_asset_profit_hist_extractor("asset_profit_hist_range"))
SECURITIES_PRESETS.register("stock_profit_ranking", _stock_profit_ranking_extractor)
SECURITIES_PRESETS.register("stock_daily_profit_range", _make_stock_daily_profit_extractor("stock_daily_profit_range"))
SECURITIES_PRESETS.register("stock_daily_profit_month", _make_stock_daily_profit_extractor("stock_daily_profit_month"))
