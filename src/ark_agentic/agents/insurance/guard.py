"""
保险智能体准入检查

使用 LLM 快速判断用户输入是否在保险业务受理范围内。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from ark_agentic.core.guard import GuardResult

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "你是一个保险业务准入分类器。判断用户输入是否与保险业务相关"
    "（保单查询、理赔、缴费、退保、保险咨询、保险产品等）。\n"
    '相关返回 {"accepted":true}，'
    '不相关返回 {"accepted":false,"message":"一句话说明"}。\n'
    "只返回 JSON，不要任何其他内容。"
)


class InsuranceIntakeGuard:
    """保险业务准入检查：单次 LLM 调用判断输入是否在受理范围。"""

    def __init__(self, llm: BaseChatModel) -> None:
        self._llm = llm

    async def check(
        self, user_input: str, context: dict[str, Any] | None = None,
    ) -> GuardResult:
        try:
            response = await self._llm.ainvoke([
                SystemMessage(content=_SYSTEM_PROMPT),
                HumanMessage(content=user_input),
            ])
            raw = (response.content or "").strip()
            data = json.loads(raw)
            return GuardResult(
                accepted=bool(data.get("accepted", True)),
                message=data.get("message"),
            )
        except Exception as e:
            logger.warning("Intake guard LLM call failed, defaulting to accepted: %s", e)
            return GuardResult(accepted=True)
