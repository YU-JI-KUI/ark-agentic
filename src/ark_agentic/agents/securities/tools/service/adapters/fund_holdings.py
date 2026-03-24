"""基金理财持仓服务适配器"""

from __future__ import annotations

import logging
from typing import Any

from ..base import (
    BaseServiceAdapter,
    ServiceError,
    require_context_fields,
)
from ..field_extraction import extract_fund_holdings

logger = logging.getLogger(__name__)


class FundHoldingsAdapter(BaseServiceAdapter):
    """基金理财持仓服务适配器

    HTTP GET，query params 传递 usercode 和 channel
    """

    http_method = "GET"

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
        require_context_fields(
            context, ["validatedata", "usercode", "channel"], "fund_holdings"
        )

        param_config = SERVICE_PARAM_CONFIGS.get("fund_holdings", {})
        query = build_api_request(param_config, context)

        headers = {"Content-Type": "application/json"}
        header_config = SERVICE_HEADER_CONFIGS.get("fund_holdings", {})
        auth_headers = build_api_headers_with_validatedata(header_config, context)
        headers.update(auth_headers)

        if self.config.auth_type == "header" and self.config.auth_value:
            if self.config.auth_key not in headers:
                headers[self.config.auth_key] = self.config.auth_value

        return headers, query

    def _normalize_response(
        self,
        raw_data: dict[str, Any],
        account_type: str,
    ) -> dict[str, Any]:
        from pydantic import ValidationError

        from ....schemas import FundHoldingsSchema

        data = raw_data.get("data", {})

        try:
            schema = FundHoldingsSchema.from_raw_data(data)
            return extract_fund_holdings(schema.model_dump())
        except ValidationError as e:
            logger.error(f"Fund holdings data validation failed: {e}")
            raise ServiceError(f"Invalid fund data: {e}")
