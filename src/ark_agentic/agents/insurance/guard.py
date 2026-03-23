"""
保险智能体准入检查

使用 LLM 快速判断用户输入是否在保险业务受理范围内。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from ark_agentic.core.guard import GuardResult

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "你是保险业务准入分类器。根据对话上下文，判断最新一条用户输入是否属于受理范围。\n"
    "【受理】满足以下任一条件：\n"
    "1. 领钱/取款：红利、生存金、保单贷款、部分领取、退保、取款方案制定/调整/查询；\n"
    "2. 保单与信息查询：个人信息、保单列表、持有产品、额度明细、办理取款操作；\n"
    "3. 上下文有保险话题时：简单问候、肯定/否定回复、指代性表达（"这个""继续"等）；\n"
    "【拒绝】与保险无关且上下文无保险话题延续。\n"
    '受理返回 {"accepted":true}，'
    '拒绝返回 {"accepted":false,"message":"<15字拒绝原因>"}。\n'
    "只返回 JSON，不要任何其他内容。"
)

_ROLE_MAP = {"user": HumanMessage, "assistant": AIMessage}


class InsuranceIntakeGuard:
    """保险业务准入检查：单次 LLM 调用判断输入是否在受理范围。"""

    def __init__(self, llm: BaseChatModel) -> None:
        self._llm = llm

    async def check(
        self,
        user_input: str,
        context: dict[str, Any] | None = None,
        history: list[dict[str, str]] | None = None,
    ) -> GuardResult:
        messages: list[BaseMessage] = [SystemMessage(content=_SYSTEM_PROMPT)]
        if history:
            for msg in history:
                cls = _ROLE_MAP.get(msg.get("role", ""), HumanMessage)
                messages.append(cls(content=msg.get("content", "")))
        messages.append(HumanMessage(content=user_input))

        try:
            response = await self._llm.ainvoke(messages)
            raw = (response.content or "").strip()
            data = json.loads(raw)
            return GuardResult(
                accepted=bool(data.get("accepted", True)),
                message=data.get("message"),
            )
        except Exception as e:
            logger.warning("Intake guard LLM call failed, defaulting to accepted: %s", e)
            return GuardResult(accepted=True)
