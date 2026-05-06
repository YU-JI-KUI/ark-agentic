"""ChannelFlowTool — 三步渠道办理状态机（单工具，按 action 分发）。

LLM 只调本工具——状态变更与 ChannelStepCard 渲染**原子**完成，
不会出现 render 看到旧 state 的并发问题。

发出 A2UI 卡片的 action：``start`` / ``confirm_policy`` / ``confirm_amount``
/ ``back``；纯文本 + STOP-CONTINUE 的 action：``confirm_bank`` / ``interrupt``。
"""

from __future__ import annotations

import itertools
import logging
import uuid
from typing import Any

from ark_agentic.core.a2ui.blocks import _comp
from ark_agentic.core.a2ui.theme import A2UITheme
from ark_agentic.core.tools.base import AgentTool, ToolParameter
from ark_agentic.core.types import AgentToolResult, ToolCall

logger = logging.getLogger(__name__)

_ENGLISH_CHANNELS: tuple[str, ...] = ("survival_fund", "bonus", "policy_loan")

_CHANNEL_CN: dict[str, str] = {
    "survival_fund": "生存金领取",
    "bonus": "红利领取",
    "policy_loan": "保单贷款",
}

# 中文别名 → 英文 ID。开源模型常把"红利"直接写进 channel 参数；
# 在工具入口接受所有合理别名再 normalize，比让模型记住映射稳得多。
_CHANNEL_ALIASES: dict[str, str] = {
    "survival_fund": "survival_fund",
    "生存金": "survival_fund",
    "生存金领取": "survival_fund",
    "bonus": "bonus",
    "红利": "bonus",
    "红利领取": "bonus",
    "policy_loan": "policy_loan",
    "保单贷款": "policy_loan",
    "贷款": "policy_loan",
}

_VALID_CHANNEL_INPUTS: tuple[str, ...] = tuple(_CHANNEL_ALIASES.keys())

_ACTIONS: tuple[str, ...] = (
    "start",
    "confirm_policy",
    "confirm_amount",
    "confirm_bank",
    "back",
    "interrupt",
)

_DEFAULT_BANK_CARD = "6225 **** 1234"

_STEP_ORDER: tuple[str, ...] = ("policy", "amount", "bank_card", "done")

_STEP_TITLES_CN: dict[str, str] = {
    "policy": "保单确认",
    "amount": "金额确认",
    "bank_card": "银行卡确认",
}

_ACTION_TO_EXPECTED_STEP: dict[str, str] = {
    "confirm_policy": "policy",
    "confirm_amount": "amount",
    "confirm_bank": "bank_card",
}

_BACK_TRANSITIONS: dict[str, str] = {
    "amount": "policy",
    "bank_card": "amount",
}

# action 是否需要在响应里附 ChannelStepCard
_RENDER_AFTER: frozenset[str] = frozenset({
    "start", "confirm_policy", "confirm_amount", "back",
})


def _normalize_channel(raw: str) -> str | None:
    return _CHANNEL_ALIASES.get(raw.strip())


def _read_state(ctx: dict[str, Any]) -> dict[str, Any]:
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


def _digest(action_label: str, channel: str, state: dict[str, Any], **extra: Any) -> str:
    """统一 digest 格式，永远带 active_channel=，便于 LLM 单字段定位。"""
    parts = [f"channel={channel}"]
    flow = state["channel_flows"].get(channel) or {}
    if "step" in flow:
        parts.append(f"step={flow['step']}")
    parts.append(f"active_channel={state.get('active_channel') or 'none'}")
    for k, v in extra.items():
        parts.append(f"{k}={v}")
    return f"[渠道流:{action_label} {' '.join(parts)}]"


class ChannelFlowTool(AgentTool):
    name = "channel_flow"
    description = (
        "渠道办理三步状态机：保单 → 金额 → 银行卡。"
        "本工具同时完成状态变更与卡片渲染；LLM 不需要再调 render_a2ui。\n"
        "- channel: 办理渠道，支持中英文（如 bonus 或 红利）\n"
        "- action 严格枚举：\n"
        "  * start：启动新流程或恢复 paused 渠道（自动暂停其他 active）\n"
        "  * confirm_policy：step=policy → amount\n"
        "  * confirm_amount：step=amount → bank_card（自动填银行卡）\n"
        "  * confirm_bank：step=bank_card → done（不再出卡片）\n"
        "  * back：amount→policy；bank_card→amount（清银行卡）\n"
        "  * interrupt：暂停当前 active 渠道，保留 step（不再出卡片）"
    )
    thinking_hint = "正在更新办理流程…"
    parameters = [
        ToolParameter(
            name="channel",
            type="string",
            description=(
                "办理渠道；支持中英文："
                "survival_fund/生存金/生存金领取，"
                "bonus/红利/红利领取，"
                "policy_loan/保单贷款/贷款。"
            ),
            enum=list(_VALID_CHANNEL_INPUTS),
        ),
        ToolParameter(
            name="action",
            type="string",
            description="状态机动作；必须为下列字符串之一。",
            enum=list(_ACTIONS),
        ),
    ]

    def __init__(
        self,
        theme: A2UITheme | None = None,
        components: dict[str, Any] | None = None,
    ) -> None:
        self._theme = theme or A2UITheme()
        if components is None:
            from ..a2ui.components import create_insurance_components
            components = create_insurance_components(self._theme)
        self._components = components

    # ---- public dispatcher ----

    async def execute(
        self, tool_call: ToolCall, context: dict[str, Any] | None = None,
    ) -> AgentToolResult:
        raw_channel: str = tool_call.arguments.get("channel", "")
        action: str = tool_call.arguments.get("action", "")
        channel = _normalize_channel(raw_channel)
        if not channel:
            return AgentToolResult.error_result(
                tool_call.id,
                f"不支持的渠道: {raw_channel}。"
                f"可用：生存金 / 红利 / 保单贷款。",
            )
        if action not in _ACTIONS:
            return AgentToolResult.error_result(
                tool_call.id,
                f"未知 action: {action}。可用：{', '.join(_ACTIONS)}",
            )

        ctx = context or {}
        state = _read_state(ctx)
        existing = state["channel_flows"].get(channel)
        if existing and existing.get("status") == "submitted":
            return AgentToolResult.error_result(
                tool_call.id, f"{_CHANNEL_CN[channel]} 已提交，无法再操作。",
            )

        if action == "start":
            return self._handle_start(tool_call, ctx, state, channel, existing)
        if action == "interrupt":
            return self._handle_interrupt(tool_call, state, channel, existing)
        if action == "back":
            return self._handle_back(tool_call, state, channel, existing)
        return self._handle_confirm(tool_call, ctx, state, channel, action, existing)

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
            content = (
                f"已恢复{_CHANNEL_CN[channel]}办理，"
                f"当前在第 {_STEP_ORDER.index(cur_step) + 1} 步。"
            )
            label = "恢复"
        else:
            seed = _seed_from_allocations(channel, ctx)
            if seed is None:
                return AgentToolResult.error_result(
                    tool_call.id,
                    f"{_CHANNEL_CN[channel]} 在当前方案中没有分配。"
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
            content = f"开始{_CHANNEL_CN[channel]}办理，第 1 步：请确认保单。"
            label = "启动"

        state["active_channel"] = channel
        return self._render(tool_call, state, channel, content, label, ctx)

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
        digest = _digest("暂停", channel, state)
        content = f"已暂停{_CHANNEL_CN[channel]}办理，需要时随时回来。"
        return AgentToolResult.json_result(
            tool_call_id=tool_call.id,
            data=content,
            metadata={"state_delta": {"_channel_flows": state}},
            llm_digest=digest,
        )

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
        content = f"已返回上一步：{_STEP_TITLES_CN[prev]}。"
        return self._render(tool_call, state, channel, content, "回退", {})

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
            return self._render(
                tool_call, state, channel,
                "保单已确认，进入第 2 步：金额确认。",
                "推进", {},
            )

        if action == "confirm_amount":
            existing["step"] = "bank_card"
            existing["bank_card"] = _DEFAULT_BANK_CARD
            return self._render(
                tool_call, state, channel,
                "金额已确认，进入第 3 步：选择收款银行卡。",
                "推进", {},
            )

        # confirm_bank
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

        digest = _digest(
            "已提交", channel, state,
            remaining=f"[{','.join(remaining)}]",
        )
        return AgentToolResult.json_result(
            tool_call_id=tool_call.id,
            data=content,
            metadata={
                "state_delta": {
                    "_channel_flows": state,
                    "_submitted_channels": sorted(already),
                },
            },
            llm_digest=digest,
        )

    # ---- render helper ----

    def _render(
        self,
        tool_call: ToolCall,
        state: dict[str, Any],
        channel: str,
        content: str,
        label: str,
        ctx: dict[str, Any],
    ) -> AgentToolResult:
        """Build ChannelStepCard A2UI payload from the *new* state and emit
        a2ui_result. Avoids the same-turn state_delta race because we use
        the freshly mutated state directly, not ctx.
        """
        builder = self._components.get("ChannelStepCard")
        if builder is None:
            return AgentToolResult.json_result(
                tool_call_id=tool_call.id,
                data=content,
                metadata={"state_delta": {"_channel_flows": state}},
                llm_digest=_digest(label, channel, state),
            )

        counter = itertools.count(1)

        def id_gen(prefix: str) -> str:
            return f"{prefix.lower()}-{next(counter):03d}"

        raw_data = {
            "channel_flows": state["channel_flows"],
            "active_channel": state.get("active_channel"),
        }
        output = builder({"channel": channel}, id_gen, raw_data)

        if not output.components:
            return AgentToolResult.json_result(
                tool_call_id=tool_call.id,
                data=content,
                metadata={"state_delta": {"_channel_flows": state}},
                llm_digest=_digest(label, channel, state),
            )

        root_id = id_gen("root")
        root = _comp(root_id, "Column", {
            "width": 100,
            "backgroundColor": self._theme.page_bg,
            "padding": self._theme.root_padding,
            "gap": self._theme.root_gap,
            "children": {"explicitList": [output.components[0]["id"]]},
        })

        session_prefix = str(ctx.get("session_id", "") or "channelflow")[:8]
        surface_id = f"chflow-{session_prefix}-{uuid.uuid4().hex[:8]}"

        payload = {
            "event": "beginRendering",
            "version": "1.0.0",
            "surfaceId": surface_id,
            "rootComponentId": root_id,
            "style": "default",
            "data": {},
            "components": [root] + output.components,
        }

        digest_text = output.llm_digest or _digest(label, channel, state)
        # 在 ChannelStepCard 自己的 digest 后追加 active_channel 字段，
        # 让 LLM 永远能用单字段查到当前在哪。
        if "active_channel=" not in digest_text:
            digest_text = (
                digest_text.rstrip("]")
                + f" active_channel={state.get('active_channel') or 'none'}]"
            )

        return AgentToolResult.a2ui_result(
            tool_call_id=tool_call.id,
            data=payload,
            metadata={"state_delta": {"_channel_flows": state}},
            llm_digest=digest_text,
        )
