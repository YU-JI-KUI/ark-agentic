"""ChannelFlowTool — 三步渠道办理状态机（单工具，按 action 分发）。

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

LLM 不直接写这块状态——只调 ``channel_flow(channel, action)``。三步卡片
本身就是完整的「办理」过程；``confirm_bank`` 不再触发外部 RPA，也不 STOP，
agent 自然继续根据 digest 决定是否追问剩余 paused 渠道。
"""

from __future__ import annotations

import logging
from typing import Any

from ark_agentic.core.tools.base import AgentTool, ToolParameter
from ark_agentic.core.types import AgentToolResult, ToolCall

logger = logging.getLogger(__name__)

_VALID_CHANNELS: tuple[str, ...] = ("survival_fund", "bonus", "policy_loan")

_ACTIONS: tuple[str, ...] = (
    "start",            # 启动或恢复（已有则保留 step）
    "confirm_policy",   # step: policy → amount
    "confirm_amount",   # step: amount → bank_card，自动填 bank_card
    "confirm_bank",     # step: bank_card → done，status=submitted
    "back",             # step: amount→policy；bank_card→amount（清 bank_card）
    "interrupt",        # 暂停当前 active；保留 step
)

_BACK_TRANSITIONS: dict[str, str] = {
    "amount": "policy",
    "bank_card": "amount",
}

_STEP_TITLES_CN: dict[str, str] = {
    "policy": "保单确认",
    "amount": "金额确认",
    "bank_card": "银行卡确认",
}

_CHANNEL_CN: dict[str, str] = {
    "survival_fund": "生存金领取",
    "bonus": "红利领取",
    "policy_loan": "保单贷款",
}

_DEFAULT_BANK_CARD = "6225 **** 1234"

_STEP_ORDER: tuple[str, ...] = ("policy", "amount", "bank_card", "done")

_ACTION_TO_EXPECTED_STEP: dict[str, str] = {
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
    """从 ``_plan_allocations`` 找该 channel 的首条分配。"""
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
    flows = state["channel_flows"]
    active = state.get("active_channel")
    if active and active != keep and active in flows:
        if flows[active].get("status") == "active":
            flows[active]["status"] = "paused"


def _ok(
    tool_call_id: str,
    state: dict[str, Any],
    content: str,
    digest: str,
    extra_delta: dict[str, Any] | None = None,
) -> AgentToolResult:
    delta: dict[str, Any] = {"_channel_flows": state}
    if extra_delta:
        delta.update(extra_delta)
    return AgentToolResult.json_result(
        tool_call_id=tool_call_id,
        data=content,
        metadata={"state_delta": delta},
        llm_digest=digest,
    )


class ChannelFlowTool(AgentTool):
    name = "channel_flow"
    description = (
        "渠道办理三步状态机。"
        "action=start 启动或恢复办理（已存在的 paused/active 流程保留 step）；"
        "confirm_policy/confirm_amount/confirm_bank 推进 step；"
        "interrupt 暂停当前 active 渠道（保留 step，可后续恢复）。"
        "其他 active 渠道在 start 时自动暂停。confirm_bank 完成后状态转 "
        "submitted，agent 根据 digest 中 remaining=[…] 决定是否追问续办。"
    )
    thinking_hint = "正在更新办理流程…"
    parameters = [
        ToolParameter(
            name="channel",
            type="string",
            description="办理渠道：survival_fund / bonus / policy_loan。",
            enum=list(_VALID_CHANNELS),
        ),
        ToolParameter(
            name="action",
            type="string",
            description="状态机动作。",
            enum=list(_ACTIONS),
        ),
    ]

    async def execute(
        self, tool_call: ToolCall, context: dict[str, Any] | None = None,
    ) -> AgentToolResult:
        channel: str = tool_call.arguments.get("channel", "")
        action: str = tool_call.arguments.get("action", "")
        if channel not in _VALID_CHANNELS:
            return AgentToolResult.error_result(
                tool_call.id,
                f"不支持的渠道: {channel}，支持: {', '.join(_VALID_CHANNELS)}",
            )
        if action not in _ACTIONS:
            return AgentToolResult.error_result(
                tool_call.id,
                f"未知 action: {action}，支持: {', '.join(_ACTIONS)}",
            )

        ctx = context or {}
        state = _read_state(ctx)
        flows = state["channel_flows"]
        existing = flows.get(channel)

        if existing and existing.get("status") == "submitted":
            return AgentToolResult.error_result(
                tool_call.id,
                f"{_CHANNEL_CN[channel]} 已提交，无法再操作。",
            )

        if action == "start":
            return self._handle_start(tool_call, ctx, state, channel, existing)

        if action == "interrupt":
            return self._handle_interrupt(tool_call, state, channel, existing)

        if action == "back":
            return self._handle_back(tool_call, state, channel, existing)

        return self._handle_confirm(
            tool_call, ctx, state, channel, action, existing,
        )

    # ---- handlers ----

    def _handle_start(
        self,
        tool_call: ToolCall,
        ctx: dict[str, Any],
        state: dict[str, Any],
        channel: str,
        existing: dict[str, Any] | None,
    ) -> AgentToolResult:
        _pause_other_active(state, keep=channel)

        if existing:
            existing["status"] = "active"
            cur_step = existing.get("step", "policy")
            digest = f"[渠道流:恢复 channel={channel} step={cur_step}]"
            content = (
                f"已恢复{_CHANNEL_CN[channel]}办理，"
                f"当前在第 {_STEP_ORDER.index(cur_step) + 1} 步。"
            )
        else:
            seed = _seed_from_allocations(channel, ctx)
            if seed is None:
                return AgentToolResult.error_result(
                    tool_call.id,
                    f"未在当前方案中找到 {_CHANNEL_CN[channel]} 的分配，"
                    "请先生成包含该渠道的取款方案。",
                )
            policy_no, amount = seed
            state["channel_flows"][channel] = {
                "step": "policy",
                "policy_no": policy_no,
                "amount": amount,
                "bank_card": None,
                "status": "active",
            }
            digest = f"[渠道流:启动 channel={channel} step=policy]"
            content = f"开始{_CHANNEL_CN[channel]}办理，第 1 步：请确认保单。"

        state["active_channel"] = channel
        return _ok(tool_call.id, state, content, digest)

    def _handle_interrupt(
        self,
        tool_call: ToolCall,
        state: dict[str, Any],
        channel: str,
        existing: dict[str, Any] | None,
    ) -> AgentToolResult:
        if not existing:
            return AgentToolResult.error_result(
                tool_call.id,
                f"{_CHANNEL_CN[channel]} 没有进行中的办理。",
            )
        existing["status"] = "paused"
        state["active_channel"] = None
        digest = (
            f"[渠道流:暂停 channel={channel} step={existing.get('step')}]"
        )
        content = f"已暂停{_CHANNEL_CN[channel]}办理，可继续办理其他渠道。"
        return _ok(tool_call.id, state, content, digest)

    def _handle_back(
        self,
        tool_call: ToolCall,
        state: dict[str, Any],
        channel: str,
        existing: dict[str, Any] | None,
    ) -> AgentToolResult:
        if not existing:
            return AgentToolResult.error_result(
                tool_call.id,
                f"{_CHANNEL_CN[channel]} 流程未启动，请先 action=start。",
            )
        cur_step = existing.get("step")
        prev = _BACK_TRANSITIONS.get(cur_step or "")
        if prev is None:
            return AgentToolResult.error_result(
                tool_call.id,
                f"{_CHANNEL_CN[channel]} 当前 step={cur_step}，无法后退。",
            )
        existing["step"] = prev
        if cur_step == "bank_card":
            existing["bank_card"] = None
        return _ok(
            tool_call.id, state,
            f"已返回上一步：{_STEP_TITLES_CN[prev]}。",
            f"[渠道流:回退 channel={channel} step={prev}]",
        )

    def _handle_confirm(
        self,
        tool_call: ToolCall,
        ctx: dict[str, Any],
        state: dict[str, Any],
        channel: str,
        action: str,
        existing: dict[str, Any] | None,
    ) -> AgentToolResult:
        if not existing:
            return AgentToolResult.error_result(
                tool_call.id,
                f"{_CHANNEL_CN[channel]} 流程未启动，请先 action=start。",
            )
        expected = _ACTION_TO_EXPECTED_STEP[action]
        cur_step = existing.get("step")
        if cur_step != expected:
            return AgentToolResult.error_result(
                tool_call.id,
                f"{_CHANNEL_CN[channel]} 当前 step={cur_step}，"
                f"无法执行 {action}",
            )

        if action == "confirm_policy":
            existing["step"] = "amount"
            return _ok(
                tool_call.id, state,
                "保单已确认，进入第 2 步：金额确认。",
                f"[渠道流:推进 channel={channel} step=amount]",
            )

        if action == "confirm_amount":
            existing["step"] = "bank_card"
            existing["bank_card"] = _DEFAULT_BANK_CARD
            return _ok(
                tool_call.id, state,
                "金额已确认，进入第 3 步：选择收款银行卡。",
                f"[渠道流:推进 channel={channel} step=bank_card]",
            )

        # action == "confirm_bank"
        existing["step"] = "done"
        existing["status"] = "submitted"
        state["active_channel"] = None

        already = list(ctx.get("_submitted_channels") or [])
        if channel not in already:
            already.append(channel)

        remaining = [
            ch for ch, f in state["channel_flows"].items()
            if f.get("status") == "paused" and ch not in already
        ]

        cn = _CHANNEL_CN[channel]
        content = f"{cn}办理已完成"
        if remaining:
            parts = [_CHANNEL_CN.get(c, c) for c in remaining]
            content += f"。还有{'、'.join(parts)}待继续办理"

        digest = (
            f"[渠道流:已提交 channel={channel} "
            f"remaining=[{','.join(remaining)}]]"
        )
        return _ok(
            tool_call.id, state, content, digest,
            extra_delta={"_submitted_channels": sorted(already)},
        )
