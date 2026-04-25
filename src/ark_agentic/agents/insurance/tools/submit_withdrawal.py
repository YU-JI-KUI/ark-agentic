"""SubmitWithdrawalTool — 确认办理取款后提交业务流程

用户明确确认办理后，LLM 调用此工具：
1. 从 session state 的 _plan_allocations 中读取对应渠道的保单和金额
2. 检查同方案中是否有未提交的渠道，写入 _submitted_channels 供下轮续办
3. 发送 CUSTOM 事件 (start_flow) 到前端
4. 返回 STOP 终止 agent loop，STOP content 包含剩余渠道提醒（跨轮桥梁）

LLM 只需传 operation_type，保单和金额由工具自动从方案数据中获取。
"""

from __future__ import annotations

import logging
from typing import Any

from ark_agentic.core.tools.base import AgentTool, ToolParameter
from ark_agentic.core.types import (
    AgentToolResult,
    CustomToolEvent,
    ToolCall,
    ToolLoopAction,
)

logger = logging.getLogger(__name__)

_SOURCE_TYPE_MAP: dict[str, str] = {
    "shengcunjin": "shengcunjin-claim-E031",
    "bonus": "bonus-claim",
    "loan": "E027Flow",
    "partial": "U045Flow",
    "surrender": "surrender",
}

_OP_TO_CHANNEL: dict[str, str] = {
    "shengcunjin": "survival_fund",
    "bonus": "bonus",
    "loan": "policy_loan",
    "partial": "partial_withdrawal",
    "surrender": "surrender",
}

_CHANNEL_CN: dict[str, str] = {
    "survival_fund": "生存金领取",
    "bonus": "红利领取",
    "policy_loan": "保单贷款",
    "partial_withdrawal": "部分领取",
    "surrender": "退保",
}


def _resolve_policies_from_state(
    operation_type: str, ctx: dict[str, Any],
) -> list[dict[str, str]] | None:
    """从 _plan_allocations 中查找匹配渠道的保单列表。"""
    channel = _OP_TO_CHANNEL.get(operation_type)
    if not channel:
        return None
    plan_allocations: list[dict[str, Any]] = ctx.get("_plan_allocations") or []
    for plan in plan_allocations:
        matching = [
            a for a in plan.get("allocations", [])
            if a.get("channel") == channel
        ]
        if matching:
            return [
                {"policy_no": a["policy_no"], "amount": str(a["amount"])}
                for a in matching
            ]
    return None


def _find_remaining_channels(
    submitted_channel: str, ctx: dict[str, Any],
) -> list[dict[str, Any]]:
    """在同一方案中查找尚未提交的渠道分配。"""
    plan_allocations: list[dict[str, Any]] = ctx.get("_plan_allocations") or []
    already_submitted = set(ctx.get("_submitted_channels") or [])
    already_submitted.add(submitted_channel)

    for plan in plan_allocations:
        plan_channels = {
            a.get("channel") for a in plan.get("allocations", [])
        }
        if submitted_channel in plan_channels:
            return [
                a for a in plan.get("allocations", [])
                if a.get("channel") not in already_submitted
            ]
    return []


def _build_stop_message(
    channel: str,
    remaining: list[dict[str, Any]],
) -> str:
    """构建 STOP content 纯文本消息。"""
    cn_name = _CHANNEL_CN.get(channel, channel)
    msg = f"已启动{cn_name}办理流程"

    if remaining:
        parts: list[str] = []
        seen: set[str] = set()
        for alloc in remaining:
            ch = alloc.get("channel", "")
            if ch in seen:
                continue
            seen.add(ch)
            amt = alloc.get("amount", 0)
            ch_cn = _CHANNEL_CN.get(ch, ch)
            parts.append(f"{ch_cn}(¥{float(amt):,.2f})")
        if parts:
            msg += f"。还有{'、'.join(parts)}待办理"

    return msg


def _build_submit_digest(
    channel: str,
    remaining: list[dict[str, Any]],
) -> str:
    """结构化 LLM digest：供 execute_withdrawal STEP 0 做字段匹配续办判定。

    格式：``[办理:已提交 channel=<ch> remaining=[<ch1>,<ch2>]]``
    """
    remaining_channels: list[str] = []
    seen: set[str] = set()
    for alloc in remaining:
        ch = alloc.get("channel", "")
        if ch and ch not in seen:
            seen.add(ch)
            remaining_channels.append(ch)
    return f"[办理:已提交 channel={channel} remaining=[{','.join(remaining_channels)}]]"


class SubmitWithdrawalTool(AgentTool):
    name = "submit_withdrawal"
    description = (
        "[STOP] 用户明确确认办理取款操作后调用。"
        "只需传 operation_type，保单、金额和用户文字由工具自动生成。"
    )
    thinking_hint = "正在提交办理请求…"
    parameters = [
        ToolParameter(
            name="operation_type",
            type="string",
            description="取款类型",
            enum=list(_SOURCE_TYPE_MAP.keys()),
        ),
    ]

    async def execute(
        self, tool_call: ToolCall, context: dict[str, Any] | None = None
    ) -> AgentToolResult:
        operation_type: str = tool_call.arguments.get("operation_type", "")
        ctx = context or {}

        source_type = _SOURCE_TYPE_MAP.get(operation_type)
        if source_type is None:
            return AgentToolResult.error_result(
                tool_call.id,
                f"未知的操作类型: {operation_type}，支持: {', '.join(_SOURCE_TYPE_MAP.keys())}",
            )

        channel = _OP_TO_CHANNEL.get(operation_type, operation_type)
        already_submitted: set[str] = set(ctx.get("_submitted_channels") or [])
        if channel in already_submitted:
            cn_name = _CHANNEL_CN.get(channel, channel)
            return AgentToolResult.json_result(
                tool_call_id=tool_call.id,
                data=f"{cn_name}已提交办理，无需重复操作。如需重新办理请先生成新的取款方案。",
                loop_action=ToolLoopAction.STOP,
            )

        policies = _resolve_policies_from_state(operation_type, ctx)
        if not policies:
            plan_allocs: list[dict] = ctx.get("_plan_allocations") or []
            available: set[str] = set()
            for p in plan_allocs:
                for a in p.get("allocations", []):
                    ch = a.get("channel")
                    if ch:
                        available.add(ch)
            return AgentToolResult.error_result(
                tool_call.id,
                f"渠道 '{channel}' 在当前方案中没有分配额度。"
                f"可用渠道: {', '.join(sorted(available)) if available else '无'}。"
                f"请先通过取款方案确认该渠道的可取额度。",
            )

        remaining = _find_remaining_channels(channel, ctx)
        already = already_submitted | {channel}
        content = _build_stop_message(channel, remaining)
        digest = _build_submit_digest(channel, remaining)

        query_msg = "，".join(
            f"保单号-{p['policy_no']}，金额-{p['amount']}"
            for p in policies
        )

        return AgentToolResult.json_result(
            tool_call_id=tool_call.id,
            data=content,
            metadata={"state_delta": {"_submitted_channels": sorted(already)}},
            loop_action=ToolLoopAction.STOP,
            events=[
                CustomToolEvent(
                    custom_type="start_flow",
                    payload={"flow_type": source_type, "query_msg": query_msg},
                ),
            ],
            llm_digest=digest,
        )
