"""账户总资产服务适配器"""

from __future__ import annotations

from typing import Any

from ..base import (
    BaseServiceAdapter,
    ServiceConfig,
    ServiceError,
    require_context_fields,
)


class AccountOverviewAdapter(BaseServiceAdapter):
    """账户总资产服务适配器

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
        require_context_fields(context, ["validatedata"], "account_overview")

        if "account_type" not in context:
            context = {**context, "account_type": account_type}

        config = SERVICE_PARAM_CONFIGS.get("account_overview", {})
        body = build_api_request(config, context)

        headers = {"Content-Type": "application/json"}
        header_config = SERVICE_HEADER_CONFIGS.get("account_overview", {})
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
        if raw_data.get("status") != 1:
            error_msg = raw_data.get("errmsg") or "Unknown API error"
            raise ServiceError(f"API returned error: {error_msg}")
        return raw_data
