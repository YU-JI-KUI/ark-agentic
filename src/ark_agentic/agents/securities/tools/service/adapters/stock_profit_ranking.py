"""用户股票盈亏排行服务适配器"""

from __future__ import annotations

from typing import Any

from ..base import (
    BaseServiceAdapter,
    build_validatedata_request,
    check_api_response,
    require_context_fields,
)
from ..field_extraction import extract_stock_profit_ranking


class StockProfitRankingAdapter(BaseServiceAdapter):
    """用户股票盈亏排行服务适配器

    仅支持普通账户。
    使用 validatedata + signature 认证。
    """

    def _build_request(
        self,
        account_type: str,
        user_id: str,
        params: dict[str, Any],
    ) -> tuple[dict[str, str], dict[str, Any]]:
        context = params.get("_context", {})
        require_context_fields(context, ["validatedata"], "stock_profit_ranking")

        headers, body = build_validatedata_request("stock_profit_ranking", context)

        if self.config.auth_type == "header" and self.config.auth_value:
            if self.config.auth_key not in headers:
                headers[self.config.auth_key] = self.config.auth_value

        return headers, body

    def _normalize_response(
        self,
        raw_data: dict[str, Any],
        account_type: str,
    ) -> dict[str, Any]:
        check_api_response(raw_data)
        return extract_stock_profit_ranking(raw_data)
