"""标的详情服务适配器"""

from __future__ import annotations

import logging
from typing import Any

from ..base import (
    BaseServiceAdapter,
    ServiceConfig,
    ServiceError,
    require_context_fields,
)

logger = logging.getLogger(__name__)


class SecurityDetailAdapter(BaseServiceAdapter):
    """标的详情服务适配器

    使用 validatedata + signature 认证
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
        require_context_fields(context, ["validatedata"], "security_detail")

        body = {"user_id": user_id, "account_type": account_type}

        headers = {"Content-Type": "application/json"}
        header_config = SERVICE_HEADER_CONFIGS.get("security_detail", {})
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
        from pydantic import ValidationError

        from ....schemas import SecurityDetailSchema

        data = raw_data.get("data", {})

        try:
            schema = SecurityDetailSchema.from_raw_data(data)
            return schema.model_dump()
        except ValidationError as e:
            logger.error(f"Security detail data validation failed: {e}")
            raise ServiceError(f"Invalid security data: {e}")
