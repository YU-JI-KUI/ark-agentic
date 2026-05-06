"""ChannelFlow* — 三步渠道办理状态机工具。

读写 ``ctx["_channel_flows"]``（dict 形态，顶层 merge 进 render_a2ui 的 raw_data）：

    {
        "channel_flows": {
            "<channel>": {
                "step": "policy" | "amount" | "bank_card" | "done",
                "policy_no": "POL001",
                "amount": 3000.0,
                "bank_card": "6225 **** 1234" | None,
                "status": "active" | "paused" | "submitted",
            },
        },
        "active_channel": "<channel>" | None,
    }

LLM 不直接写这块状态——只调下面三个工具，由工具完成 step 推进、字段填充
和并发 active 渠道的暂停。
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

_VALID_CHANNELS: tuple[str, ...] = ("survival_fund", "bonus", "policy_loan")

_CHANNEL_TO_OP: dict[str, str] = {
    "survival_fund": "shengcunjin",
    "bonus": "bonus",
    "policy_loan": "loan",
}

_SOURCE_TYPE_MAP: dict[str, str] = {
    "shengcunjin": "shengcunjin-claim-E031",
    "bonus": "bonus-claim",
    "loan": "E027Flow",
}

_CHANNEL_CN: dict[str, str] = {
    "survival_fund": "生存金领取",
    "bonus": "红利领取",
    "policy_loan": "保单贷款",
}

_DEFAULT_BANK_CARD = "6225 **** 1234"

_STEP_ORDER: tuple[str, ...] = ("policy", "amount", "bank_card", "done")

_ACTION_TO_STEP: dict[str, str] = {
    "confirm_policy": "policy",
    "confirm_amount": "amount",
    "confirm_bank": "bank_card",
}


def _read_state(ctx: dict[str, Any]) -> dict[str, Any]:
    """Snapshot ``_channel_flows``（深一层拷贝，便于安全写回 state_delta）。"""
    raw = ctx.get("_channel_flows") or {}
    flows_in = raw.get("channel_flows") or {}
    flows: dict[str, dict[str, Any]] = {k: dict(v) for k, v in flows_in.items()}
    return {
        "channel_flows": flows,
        "active_channel": raw.get("active_channel"),
    }


def _seed_from_allocations(
    channel: str, ctx: dict[str, Any],
) -> tuple[str, float] | None:
    """从 ``_plan_allocations`` 找该 channel 的首条分配，返回 (policy_no, amount)。"""
    plans: list[dict[str, Any]] = ctx.get("_plan_allocations") or []
    for plan in plans:
        for alloc in plan.get("allocations", []):
            if alloc.get("channel") == channel:
                policy_no = str(alloc.get("policy_no") or "")
                amount = float(alloc.get("amount") or 0)
                if policy_no and amount > 0:
                    return policy_no, amount
    return None


def _pause_other_active(state: dict[str, Any], keep: str) -> None:
    """把除 ``keep`` 外的 active 渠道置为 paused（in-place）。"""
    flows = state["channel_flows"]
    active = state.get("active_channel")
    if active and active != keep and active in flows:
        if flows[active].get("status") == "active":
            flows[active]["status"] = "paused"


def _delta(state: dict[str, Any]) -> dict[str, Any]:
    return {"_channel_flows": state}


# ---------------------------------------------------------------------------


class ChannelFlowStartTool(AgentTool):
    name = "channel_flow_start"
    description = (
        "启动或激活某渠道的三步办理流程。"
        "新建时从 step=policy 开始，自动从当前方案分配中读取保单号和金额；"
        "已存在的 paused/active 流程会被恢复到中断时的 step。"
        "其他 active 渠道自动暂停。"
    )
    thinking_hint = "正在准备办理流程…"
    parameters = [
        ToolParameter(
            name="channel",
            type="string",
            description="办理渠道：survival_fund / bonus / policy_loan。",
            enum=list(_VALID_CHANNELS),
        ),
    ]

    async def execute(
        self, tool_call: ToolCall, context: dict[str, Any] | None = None,
    ) -> AgentToolResult:
        channel: str = tool_call.arguments.get("channel", "")
        if channel not in _VALID_CHANNELS:
            return AgentToolResult.error_result(
                tool_call.id,
                f"不支持的渠道: {channel}，支持: {', '.join(_VALID_CHANNELS)}",
            )

        ctx = context or {}
        state = _read_state(ctx)
        flows = state["channel_flows"]

        existing = flows.get(channel)
        if existing and existing.get("status") == "submitted":
            return AgentToolResult.error_result(
                tool_call.id, f"{_CHANNEL_CN[channel]} 已提交，无法重复办理。",
            )

        _pause_other_active(state, keep=channel)

        if existing:
            existing["status"] = "active"
            cur_step = existing.get("step", "policy")
            digest = f"[渠道流:恢复 channel={channel} step={cur_step}]"
            content = f"已恢复{_CHANNEL_CN[channel]}办理，当前在第 {_STEP_ORDER.index(cur_step) + 1} 步。"
        else:
            seed = _seed_from_allocations(channel, ctx)
            if seed is None:
                return AgentToolResult.error_result(
                    tool_call.id,
                    f"未在当前方案中找到 {_CHANNEL_CN[channel]} 的分配，"
                    "请先生成包含该渠道的取款方案。",
                )
            policy_no, amount = seed
            flows[channel] = {
                "step": "policy",
                "policy_no": policy_no,
                "amount": amount,
                "bank_card": None,
                "status": "active",
            }
            digest = f"[渠道流:启动 channel={channel} step=policy]"
            content = f"开始{_CHANNEL_CN[channel]}办理，第 1 步：请确认保单。"

        state["active_channel"] = channel
        return AgentToolResult.json_result(
            tool_call_id=tool_call.id,
            data=content,
            metadata={"state_delta": _delta(state)},
            llm_digest=digest,
        )


# ---------------------------------------------------------------------------


class ChannelFlowAdvanceTool(AgentTool):
    name = "channel_flow_advance"
    description = (
        "推进或中断渠道办理流程。"
        "confirm_policy → step=amount；"
        "confirm_amount → step=bank_card 并自动填入银行卡；"
        "confirm_bank → 触发外部办理流程并 STOP；"
        "interrupt / cancel → 标记 paused 并清空 active_channel。"
    )
    thinking_hint = "正在更新办理状态…"
    parameters = [
        ToolParameter(
            name="channel",
            type="string",
            description="办理渠道。",
            enum=list(_VALID_CHANNELS),
        ),
        ToolParameter(
            name="action",
            type="string",
            description="动作类型。",
            enum=[
                "confirm_policy",
                "confirm_amount",
                "confirm_bank",
                "interrupt",
                "cancel",
            ],
        ),
    ]

    async def execute(
        self, tool_call: ToolCall, context: dict[str, Any] | None = None,
    ) -> AgentToolResult:
        channel: str = tool_call.arguments.get("channel", "")
        action: str = tool_call.arguments.get("action", "")
        if channel not in _VALID_CHANNELS:
            return AgentToolResult.error_result(
                tool_call.id, f"不支持的渠道: {channel}",
            )

        ctx = context or {}
        state = _read_state(ctx)
        flows = state["channel_flows"]
        flow = flows.get(channel)
        if not flow:
            return AgentToolResult.error_result(
                tool_call.id,
                f"{_CHANNEL_CN[channel]} 流程未启动，请先调 channel_flow_start。",
            )
        if flow.get("status") == "submitted":
            return AgentToolResult.error_result(
                tool_call.id, f"{_CHANNEL_CN[channel]} 已提交，无法再操作。",
            )

        if action in ("interrupt", "cancel"):
            flow["status"] = "paused"
            state["active_channel"] = None
            return AgentToolResult.json_result(
                tool_call_id=tool_call.id,
                data=f"已暂停{_CHANNEL_CN[channel]}办理，可继续办理其他渠道。",
                metadata={"state_delta": _delta(state)},
                llm_digest=(
                    f"[渠道流:暂停 channel={channel} step={flow.get('step')}]"
                ),
            )

        expected = _ACTION_TO_STEP.get(action)
        if expected is None:
            return AgentToolResult.error_result(
                tool_call.id,
                f"未知 action: {action}",
            )
        cur_step = flow.get("step")
        if cur_step != expected:
            return AgentToolResult.error_result(
                tool_call.id,
                f"{_CHANNEL_CN[channel]} 当前 step={cur_step}，无法执行 {action}",
            )

        if action == "confirm_policy":
            flow["step"] = "amount"
            return AgentToolResult.json_result(
                tool_call_id=tool_call.id,
                data="保单已确认，进入第 2 步：金额确认。",
                metadata={"state_delta": _delta(state)},
                llm_digest=f"[渠道流:推进 channel={channel} step=amount]",
            )

        if action == "confirm_amount":
            flow["step"] = "bank_card"
            flow["bank_card"] = _DEFAULT_BANK_CARD
            return AgentToolResult.json_result(
                tool_call_id=tool_call.id,
                data="金额已确认，进入第 3 步：选择收款银行卡。",
                metadata={"state_delta": _delta(state)},
                llm_digest=f"[渠道流:推进 channel={channel} step=bank_card]",
            )

        # action == "confirm_bank"：触发外部办理流程 + STOP
        flow["step"] = "done"
        flow["status"] = "submitted"
        state["active_channel"] = None

        op = _CHANNEL_TO_OP[channel]
        source_type = _SOURCE_TYPE_MAP[op]
        policy_no = str(flow.get("policy_no", ""))
        amount = float(flow.get("amount") or 0)
        query_msg = f"保单号-{policy_no}，金额-{amount:.2f}"

        already = list(ctx.get("_submitted_channels") or [])
        if channel not in already:
            already.append(channel)

        remaining = [
            ch for ch, f in flows.items()
            if f.get("status") == "paused" and ch not in already
        ]

        cn = _CHANNEL_CN[channel]
        msg = f"已启动{cn}办理流程"
        if remaining:
            parts = [_CHANNEL_CN.get(c, c) for c in remaining]
            msg += f"。还有{'、'.join(parts)}待继续办理"

        digest = (
            f"[渠道流:已提交 channel={channel} "
            f"remaining=[{','.join(remaining)}]]"
        )

        return AgentToolResult.json_result(
            tool_call_id=tool_call.id,
            data=msg,
            metadata={
                "state_delta": {
                    "_channel_flows": state,
                    "_submitted_channels": sorted(already),
                },
            },
            loop_action=ToolLoopAction.STOP,
            events=[
                CustomToolEvent(
                    custom_type="start_flow",
                    payload={"flow_type": source_type, "query_msg": query_msg},
                ),
            ],
            llm_digest=digest,
        )


# ---------------------------------------------------------------------------


class ChannelFlowResumeTool(AgentTool):
    name = "channel_flow_resume"
    description = (
        "把某 paused 渠道恢复为 active；不改变 step。"
        "若有其他 active 渠道，自动暂停。"
    )
    thinking_hint = "正在恢复办理流程…"
    parameters = [
        ToolParameter(
            name="channel",
            type="string",
            description="办理渠道。",
            enum=list(_VALID_CHANNELS),
        ),
    ]

    async def execute(
        self, tool_call: ToolCall, context: dict[str, Any] | None = None,
    ) -> AgentToolResult:
        channel: str = tool_call.arguments.get("channel", "")
        if channel not in _VALID_CHANNELS:
            return AgentToolResult.error_result(
                tool_call.id, f"不支持的渠道: {channel}",
            )

        ctx = context or {}
        state = _read_state(ctx)
        flow = state["channel_flows"].get(channel)
        if not flow:
            return AgentToolResult.error_result(
                tool_call.id,
                f"{_CHANNEL_CN[channel]} 没有进行中的办理。",
            )
        if flow.get("status") == "submitted":
            return AgentToolResult.error_result(
                tool_call.id, f"{_CHANNEL_CN[channel]} 已提交，无法恢复。",
            )

        _pause_other_active(state, keep=channel)
        flow["status"] = "active"
        state["active_channel"] = channel

        cur_step = flow.get("step", "policy")
        return AgentToolResult.json_result(
            tool_call_id=tool_call.id,
            data=(
                f"已恢复{_CHANNEL_CN[channel]}办理，"
                f"当前在第 {_STEP_ORDER.index(cur_step) + 1} 步。"
            ),
            metadata={"state_delta": _delta(state)},
            llm_digest=f"[渠道流:恢复 channel={channel} step={cur_step}]",
        )
