"""
保险智能体准入检查

使用 LLM 快速判断用户输入是否在保险取款业务受理范围内。
temperature=0 消除分类非确定性，few-shot 锚定边界 case。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from ark_agentic.core.callbacks import BeforeAgentCallback, CallbackContext
from ark_agentic.core.guard import GuardResult
from ark_agentic.core.types import AgentMessage, MessageRole

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """你是保险取款业务准入分类器。根据对话上下文，判断最新一条用户输入是否属于受理范围。

【受理范围】仅限以下业务：
1. 领钱/取款：红利领取、生存金领取、保单贷款、部分领取、退保；
2. 方案：取款方案的制定、调整、查询；
3. 相关查询：与取款直接相关的保单信息、个人信息、额度明细；
4. 上下文延续：上下文有取款相关话题时的确认、否定、指代性表达（"好的""继续""这个"等）。

【不受理】以下情况：
- 保费缴纳、理赔报案、投保咨询、续保、核保等非取款业务；
- 与保险完全无关的话题。

示例：
用户：领50000 → {"accepted":true}
用户：红利能领多少钱 → {"accepted":true}
用户：帮我做个取款方案 → {"accepted":true}
用户：保单贷款怎么办理 → {"accepted":true}
用户：好的，就这样 → {"accepted":true}（上下文延续）
用户：50000的方案 → {"accepted":true}
用户：还是第一个方案 → {"accepted":true}
用户：用卡片展示一下 → {"accepted":true}
用户：怎么理赔 → {"accepted":false,"message":"理赔非取款业务范围"}
用户：我要交保费 → {"accepted":false,"message":"保费非取款业务范围"}
用户：今天天气怎么样 → {"accepted":false,"message":"非保险业务范围"}

受理返回 {"accepted":true}，拒绝返回 {"accepted":false,"message":"<简短拒绝原因>"}。
只返回 JSON，不要任何其他内容。""".strip()

_ROLE_MAP: dict[str, type[BaseMessage]] = {"user": HumanMessage, "assistant": AIMessage}


class InsuranceIntakeGuard:
    """保险取款业务准入检查：单次 LLM 调用，temperature=0 确保确定性。"""

    _HISTORY_WINDOW = 10

    def __init__(self, llm: BaseChatModel) -> None:
        if hasattr(llm, "model_copy"):
            self._llm = llm.model_copy(update={"temperature": 0})
        elif hasattr(llm, "copy"):
            self._llm = llm.copy(update={"temperature": 0})
        else:
            self._llm = llm

    async def check(
        self,
        user_input: str,
        context: dict[str, Any] | None = None,
        history: list[AgentMessage] | None = None,
    ) -> GuardResult:
        messages: list[BaseMessage] = [SystemMessage(content=_SYSTEM_PROMPT)]
        if history:
            relevant = [
                m for m in history
                if m.role in (MessageRole.USER, MessageRole.ASSISTANT) and m.content
            ][-self._HISTORY_WINDOW:]
            messages += [_ROLE_MAP[m.role.value](content=m.content) for m in relevant]
        messages.append(HumanMessage(content=user_input))

        try:
            response = await self._llm.ainvoke(messages)
            raw = (response.content or "").strip()  # type: ignore[union-attr]
            data = json.loads(raw)
            return GuardResult(
                accepted=bool(data.get("accepted", True)),
                message=data.get("message"),
            )
        except Exception as e:
            logger.warning("Intake guard LLM call failed, defaulting to accepted: %s", e)
            return GuardResult(accepted=True)


def make_before_agent_callback(
    guard: InsuranceIntakeGuard,
    rejected_event_data: dict[str, Any] | None = None,
) -> BeforeAgentCallback:
    """将 InsuranceIntakeGuard 适配为 BeforeAgentCallback。

    Args:
        guard: 准入检查实例
        rejected_event_data: 拒绝时发送的 custom event data，默认 {"relevant": 0}
    """

    async def _cb(ctx: CallbackContext) -> tuple[AgentMessage, dict[str, Any]] | None:
        result = await guard.check(
            ctx.user_input,
            ctx.input_context,
            history=ctx.session.messages or None,
        )
        if not result.accepted:
            logger.info("Intake guard rejected: %s", result.message)
            return (
                AgentMessage.assistant(result.message or ""),
                rejected_event_data or {"relevant": 0},
            )
        return None

    return _cb  # type: ignore[return-value]
