"""开户营业部查询服务适配器"""

from __future__ import annotations

from typing import Any

from ..base import (
    BaseServiceAdapter,
    check_api_response,
    require_context_fields,
)
from ..field_extraction import extract_branch_info


class BranchInfoAdapter(BaseServiceAdapter):
    """开户营业部查询服务适配器

    使用 validatedata + signature 认证，body 为空
    """

    def _build_request(
        self,
        account_type: str,
        user_id: str,
        params: dict[str, Any],
    ) -> tuple[dict[str, str], dict[str, Any]]:
        from ..param_mapping import (
            build_api_headers_with_validatedata,
            SERVICE_HEADER_CONFIGS,
        )

        context = params.get("_context", {})
        require_context_fields(context, ["validatedata"], "branch_info")

        headers = {"Content-Type": "application/json"}
        header_config = SERVICE_HEADER_CONFIGS.get("branch_info", {})
        auth_headers = build_api_headers_with_validatedata(header_config, context)
        headers.update(auth_headers)

        if self.config.auth_type == "header" and self.config.auth_value:
            if self.config.auth_key not in headers:
                headers[self.config.auth_key] = self.config.auth_value

        return headers, {}

    def _normalize_response(
        self,
        raw_data: dict[str, Any],
        account_type: str,
    ) -> dict[str, Any]:
        check_api_response(raw_data)
        return extract_branch_info(raw_data)
