"""用户资产历史收益曲线服务适配器"""

from __future__ import annotations

from typing import Any

from ..base import (
    BaseServiceAdapter,
    ServiceError,
    build_validatedata_request,
    check_api_response,
    require_context_fields,
)
from ..field_extraction import extract_asset_profit_hist


class AssetProfitHistAdapter(BaseServiceAdapter):
    """用户资产历史收益曲线服务适配器

    支持普通账户（assetGrpType=1）和两融账户（assetGrpType=2）。
    使用 validatedata + signature 认证。
    """

    def _build_request(
        self,
        account_type: str,
        user_id: str,
        params: dict[str, Any],
    ) -> tuple[dict[str, str], dict[str, Any]]:
        context = params.get("_context", {})
        require_context_fields(context, ["validatedata"], "asset_profit_hist")

        if "account_type" not in context:
            context = {**context, "account_type": account_type}

        headers, body = build_validatedata_request("asset_profit_hist", context, account_type)

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
        return extract_asset_profit_hist(raw_data, account_type)
