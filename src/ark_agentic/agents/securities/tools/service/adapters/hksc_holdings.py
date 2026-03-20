"""港股通持仓服务适配器"""

from __future__ import annotations

from typing import Any

from ..base import (
    BaseServiceAdapter,
    check_api_response,
    require_context_fields,
)
from ..field_extraction import extract_hksc_holdings


class HKSCHoldingsAdapter(BaseServiceAdapter):
    """港股通持仓服务适配器

    使用 validatedata + signature 认证
    """

    def _build_request(
        self,
        account_type: str,
        user_id: str,
        params: dict[str, Any],
    ) -> tuple[dict[str, str], dict[str, Any]]:
        from ..param_mapping import (
            build_api_request,
            build_api_headers_with_validatedata,
            SERVICE_PARAM_CONFIGS,
            SERVICE_HEADER_CONFIGS,
        )

        context = params.get("_context", {})
        require_context_fields(context, ["validatedata"], "hksc_holdings")

        config = SERVICE_PARAM_CONFIGS.get("hksc_holdings", {})
        body = build_api_request(config, context)

        headers = {"Content-Type": "application/json"}
        header_config = SERVICE_HEADER_CONFIGS.get("hksc_holdings", {})
        auth_headers = build_api_headers_with_validatedata(header_config, context)
        headers.update(auth_headers)

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
        return extract_hksc_holdings(raw_data)
