"""Unit tests for SubmitWithdrawalTool — state-only policies, remaining-channel detection."""

import pytest

from ark_agentic.agents.insurance.tools.submit_withdrawal import (
    SubmitWithdrawalTool,
    _build_stop_message,
    _build_submit_digest,
    _find_remaining_channels,
    _resolve_policies_from_state,
)
from ark_agentic.core.types import (
    AgentToolResult,
    CustomToolEvent,
    ToolCall,
    ToolLoopAction,
    ToolResultType,
)


def _plan_ctx(
    allocations: list[dict],
    channels: list[str] | None = None,
    submitted: list[str] | None = None,
) -> dict:
    ctx: dict = {
        "_plan_allocations": [
            {
                "title": "plan",
                "channels": channels or [],
                "allocations": allocations,
            }
        ]
    }
    if submitted is not None:
        ctx["_submitted_channels"] = submitted
    return ctx


def _multi_channel_ctx(submitted: list[str] | None = None) -> dict:
    """Zero-cost plan with survival_fund + bonus."""
    return _plan_ctx(
        allocations=[
            {"channel": "survival_fund", "policy_no": "POL002", "amount": 12000},
            {"channel": "bonus", "policy_no": "POL002", "amount": 5200},
        ],
        channels=["survival_fund", "bonus"],
        submitted=submitted,
    )


class TestResolvePoliciesFromState:
    def test_matches_survival_fund_channel(self) -> None:
        ctx = _plan_ctx(
            [
                {
                    "channel": "survival_fund",
                    "policy_no": "P001",
                    "amount": 12000,
                }
            ]
        )
        out = _resolve_policies_from_state("shengcunjin", ctx)
        assert out == [{"policy_no": "P001", "amount": "12000"}]

    def test_returns_none_when_no_plan_has_channel(self) -> None:
        ctx = _plan_ctx(
            [{"channel": "bonus", "policy_no": "P1", "amount": 100}]
        )
        assert _resolve_policies_from_state("shengcunjin", ctx) is None

    def test_first_matching_plan_wins(self) -> None:
        ctx = {
            "_plan_allocations": [
                {
                    "allocations": [
                        {
                            "channel": "survival_fund",
                            "policy_no": "A",
                            "amount": 1,
                        }
                    ]
                },
                {
                    "allocations": [
                        {
                            "channel": "survival_fund",
                            "policy_no": "B",
                            "amount": 2,
                        }
                    ]
                },
            ]
        }
        out = _resolve_policies_from_state("shengcunjin", ctx)
        assert out == [{"policy_no": "A", "amount": "1"}]

    def test_multiple_rows_same_channel(self) -> None:
        ctx = _plan_ctx(
            [
                {"channel": "bonus", "policy_no": "P1", "amount": 10},
                {"channel": "bonus", "policy_no": "P2", "amount": 20},
            ]
        )
        out = _resolve_policies_from_state("bonus", ctx)
        assert out == [
            {"policy_no": "P1", "amount": "10"},
            {"policy_no": "P2", "amount": "20"},
        ]


class TestFindRemainingChannels:
    def test_single_channel_plan_returns_empty(self) -> None:
        ctx = _plan_ctx(
            [{"channel": "policy_loan", "policy_no": "P1", "amount": 5000}],
            channels=["policy_loan"],
        )
        assert _find_remaining_channels("policy_loan", ctx) == []

    def test_multi_channel_first_submit_returns_remaining(self) -> None:
        ctx = _multi_channel_ctx()
        remaining = _find_remaining_channels("survival_fund", ctx)
        assert len(remaining) == 1
        assert remaining[0]["channel"] == "bonus"
        assert remaining[0]["amount"] == 5200

    def test_multi_channel_second_submit_returns_empty(self) -> None:
        ctx = _multi_channel_ctx(submitted=["survival_fund"])
        remaining = _find_remaining_channels("bonus", ctx)
        assert remaining == []

    def test_channel_not_in_any_plan(self) -> None:
        ctx = _plan_ctx(
            [{"channel": "bonus", "policy_no": "P1", "amount": 100}],
        )
        assert _find_remaining_channels("policy_loan", ctx) == []

    def test_empty_plan_allocations(self) -> None:
        assert _find_remaining_channels("survival_fund", {}) == []

    def test_three_channel_plan_returns_two_remaining(self) -> None:
        ctx = _plan_ctx(
            [
                {"channel": "survival_fund", "policy_no": "P1", "amount": 1000},
                {"channel": "bonus", "policy_no": "P1", "amount": 500},
                {"channel": "policy_loan", "policy_no": "P1", "amount": 3000},
            ],
            channels=["survival_fund", "bonus", "policy_loan"],
        )
        remaining = _find_remaining_channels("survival_fund", ctx)
        assert len(remaining) == 2
        channels = {r["channel"] for r in remaining}
        assert channels == {"bonus", "policy_loan"}

    def test_already_submitted_channels_excluded(self) -> None:
        ctx = _plan_ctx(
            [
                {"channel": "survival_fund", "policy_no": "P1", "amount": 1000},
                {"channel": "bonus", "policy_no": "P1", "amount": 500},
                {"channel": "policy_loan", "policy_no": "P1", "amount": 3000},
            ],
            channels=["survival_fund", "bonus", "policy_loan"],
            submitted=["survival_fund"],
        )
        remaining = _find_remaining_channels("bonus", ctx)
        assert len(remaining) == 1
        assert remaining[0]["channel"] == "policy_loan"


class TestBuildStopMessage:
    def test_single_channel_no_remaining(self) -> None:
        msg = _build_stop_message("policy_loan", [])
        assert msg == "已启动保单贷款办理流程"

    def test_with_remaining_channels(self) -> None:
        remaining = [
            {"channel": "bonus", "amount": 5200},
        ]
        msg = _build_stop_message("survival_fund", remaining)
        assert "已启动生存金领取办理流程" in msg
        assert "红利领取(¥5,200.00)待办理" in msg

    def test_multiple_remaining_deduped(self) -> None:
        remaining = [
            {"channel": "bonus", "amount": 500},
            {"channel": "bonus", "amount": 700},
            {"channel": "policy_loan", "amount": 3000},
        ]
        msg = _build_stop_message("survival_fund", remaining)
        assert "红利领取" in msg
        assert "保单贷款" in msg
        assert msg.count("红利领取") == 1


class TestBuildSubmitDigest:
    """结构化 llm_digest：[办理:已提交 channel=… remaining=[…]]，供 execute_withdrawal STEP 0 续办判定。"""

    def test_no_remaining(self) -> None:
        digest = _build_submit_digest("policy_loan", [])
        assert digest == "[办理:已提交 channel=policy_loan remaining=[]]"

    def test_with_remaining(self) -> None:
        digest = _build_submit_digest(
            "survival_fund", [{"channel": "bonus", "amount": 5200}]
        )
        assert digest == "[办理:已提交 channel=survival_fund remaining=[bonus]]"

    def test_multiple_remaining_deduped(self) -> None:
        digest = _build_submit_digest(
            "survival_fund",
            [
                {"channel": "bonus", "amount": 500},
                {"channel": "bonus", "amount": 700},
                {"channel": "policy_loan", "amount": 3000},
            ],
        )
        assert digest == (
            "[办理:已提交 channel=survival_fund remaining=[bonus,policy_loan]]"
        )


class TestSubmitWithdrawalToolExecute:
    @pytest.fixture
    def tool(self) -> SubmitWithdrawalTool:
        return SubmitWithdrawalTool()

    def test_parameters(self, tool: SubmitWithdrawalTool) -> None:
        assert len(tool.parameters) == 1
        assert tool.parameters[0].name == "operation_type"

    @pytest.mark.asyncio
    async def test_happy_path_single_channel(
        self, tool: SubmitWithdrawalTool
    ) -> None:
        tc = ToolCall(
            id="c1",
            name="submit_withdrawal",
            arguments={"operation_type": "loan"},
        )
        ctx = _plan_ctx(
            [{"channel": "policy_loan", "policy_no": "L1", "amount": 5000}]
        )
        result = await tool.execute(tc, context=ctx)
        assert isinstance(result, AgentToolResult)
        assert result.result_type == ToolResultType.JSON
        assert result.loop_action == ToolLoopAction.STOP
        assert "已启动保单贷款办理流程" in str(result.content)
        assert "待办理" not in str(result.content)
        assert result.llm_digest == "[办理:已提交 channel=policy_loan remaining=[]]"
        assert len(result.events) == 1
        ev = result.events[0]
        assert isinstance(ev, CustomToolEvent)
        assert ev.custom_type == "start_flow"
        assert ev.payload["flow_type"] == "E027Flow"
        assert ev.payload["query_msg"] == "保单号-L1，金额-5000"

    @pytest.mark.asyncio
    async def test_happy_path_multi_channel_digest_carries_remaining(
        self, tool: SubmitWithdrawalTool
    ) -> None:
        tc = ToolCall(
            id="c_digest",
            name="submit_withdrawal",
            arguments={"operation_type": "shengcunjin"},
        )
        ctx = _multi_channel_ctx()
        result = await tool.execute(tc, context=ctx)
        assert result.llm_digest == (
            "[办理:已提交 channel=survival_fund remaining=[bonus]]"
        )

    @pytest.mark.asyncio
    async def test_multi_channel_first_submit_shows_remaining(
        self, tool: SubmitWithdrawalTool
    ) -> None:
        tc = ToolCall(
            id="c1",
            name="submit_withdrawal",
            arguments={"operation_type": "shengcunjin"},
        )
        ctx = _multi_channel_ctx()
        result = await tool.execute(tc, context=ctx)
        assert result.loop_action == ToolLoopAction.STOP
        assert "已启动生存金领取办理流程" in str(result.content)
        assert "红利领取" in str(result.content)
        assert "待办理" in str(result.content)

    @pytest.mark.asyncio
    async def test_multi_channel_second_submit_no_remaining(
        self, tool: SubmitWithdrawalTool
    ) -> None:
        tc = ToolCall(
            id="c1",
            name="submit_withdrawal",
            arguments={"operation_type": "bonus"},
        )
        ctx = _multi_channel_ctx(submitted=["survival_fund"])
        result = await tool.execute(tc, context=ctx)
        assert result.loop_action == ToolLoopAction.STOP
        assert "已启动红利领取办理流程" in str(result.content)
        assert "待办理" not in str(result.content)

    @pytest.mark.asyncio
    async def test_state_delta_tracks_submitted_channels(
        self, tool: SubmitWithdrawalTool
    ) -> None:
        tc = ToolCall(
            id="c1",
            name="submit_withdrawal",
            arguments={"operation_type": "shengcunjin"},
        )
        ctx = _multi_channel_ctx()
        result = await tool.execute(tc, context=ctx)
        delta = result.metadata.get("state_delta", {})
        assert "survival_fund" in delta["_submitted_channels"]

    @pytest.mark.asyncio
    async def test_state_delta_accumulates_across_turns(
        self, tool: SubmitWithdrawalTool
    ) -> None:
        tc = ToolCall(
            id="c1",
            name="submit_withdrawal",
            arguments={"operation_type": "bonus"},
        )
        ctx = _multi_channel_ctx(submitted=["survival_fund"])
        result = await tool.execute(tc, context=ctx)
        delta = result.metadata.get("state_delta", {})
        submitted = set(delta["_submitted_channels"])
        assert submitted == {"survival_fund", "bonus"}

    @pytest.mark.asyncio
    async def test_unknown_operation_type_error(
        self, tool: SubmitWithdrawalTool
    ) -> None:
        tc = ToolCall(
            id="c2",
            name="submit_withdrawal",
            arguments={"operation_type": "not_a_real_op"},
        )
        result = await tool.execute(tc, context=_plan_ctx([]))
        assert result.result_type == ToolResultType.ERROR
        assert result.is_error is True
        assert "未知的操作类型" in str(result.content)

    @pytest.mark.asyncio
    async def test_missing_state_returns_error(self, tool: SubmitWithdrawalTool) -> None:
        tc = ToolCall(
            id="c3",
            name="submit_withdrawal",
            arguments={"operation_type": "shengcunjin"},
        )
        result = await tool.execute(tc, context={})
        assert result.result_type == ToolResultType.ERROR
        assert result.is_error is True

    @pytest.mark.asyncio
    async def test_auto_generated_stop_message(
        self, tool: SubmitWithdrawalTool
    ) -> None:
        tc = ToolCall(
            id="c4",
            name="submit_withdrawal",
            arguments={"operation_type": "loan"},
        )
        ctx = _plan_ctx(
            [{"channel": "policy_loan", "policy_no": "L1", "amount": 5000}]
        )
        result = await tool.execute(tc, context=ctx)
        assert result.loop_action == ToolLoopAction.STOP
        assert "已启动保单贷款办理流程" in str(result.content)

    @pytest.mark.asyncio
    async def test_empty_context_uses_empty_dict(
        self, tool: SubmitWithdrawalTool
    ) -> None:
        tc = ToolCall(
            id="c7",
            name="submit_withdrawal",
            arguments={"operation_type": "bonus"},
        )
        result = await tool.execute(tc, context=None)
        assert result.is_error is True


class TestAntiReentryAndConvergence:
    """Prevent same channel from being submitted twice; verify all-done convergence."""

    @pytest.fixture
    def tool(self) -> SubmitWithdrawalTool:
        return SubmitWithdrawalTool()

    @pytest.mark.asyncio
    async def test_same_channel_submitted_twice_is_blocked(
        self, tool: SubmitWithdrawalTool,
    ) -> None:
        """Already-submitted channel returns early with dedup message, no state_delta."""
        ctx = _multi_channel_ctx(submitted=["survival_fund"])
        tc = ToolCall(
            id="dup1",
            name="submit_withdrawal",
            arguments={"operation_type": "shengcunjin"},
        )
        result = await tool.execute(tc, context=ctx)
        assert not result.is_error
        assert "已提交办理" in str(result.content)
        assert "无需重复" in str(result.content)
        assert result.loop_action == ToolLoopAction.STOP
        assert result.metadata.get("state_delta") is None

    @pytest.mark.asyncio
    async def test_all_channels_done_no_remaining_message(
        self, tool: SubmitWithdrawalTool,
    ) -> None:
        """After all channels submitted, stop message has no '待办理'."""
        ctx = _multi_channel_ctx(submitted=["survival_fund"])
        tc = ToolCall(
            id="all_done",
            name="submit_withdrawal",
            arguments={"operation_type": "bonus"},
        )
        result = await tool.execute(tc, context=ctx)
        assert "待办理" not in str(result.content)
        delta = result.metadata.get("state_delta", {})
        assert set(delta["_submitted_channels"]) == {"survival_fund", "bonus"}

    @pytest.mark.asyncio
    async def test_adjust_resets_submitted_then_resubmit_works(
        self, tool: SubmitWithdrawalTool,
    ) -> None:
        """Simulates ADJUST: new PlanCard resets _submitted_channels to [],
        then first submit should show remaining again."""
        ctx = _plan_ctx(
            allocations=[
                {"channel": "survival_fund", "policy_no": "POL002", "amount": 12000},
                {"channel": "bonus", "policy_no": "POL002", "amount": 5200},
            ],
            channels=["survival_fund", "bonus"],
            submitted=[],
        )
        tc = ToolCall(
            id="post_adjust",
            name="submit_withdrawal",
            arguments={"operation_type": "shengcunjin"},
        )
        result = await tool.execute(tc, context=ctx)
        assert not result.is_error
        assert "待办理" in str(result.content), "After reset, remaining channels should be shown"
        assert "红利领取" in str(result.content)

    @pytest.mark.asyncio
    async def test_three_channel_all_done_convergence(
        self, tool: SubmitWithdrawalTool,
    ) -> None:
        """Three-channel plan: submit all three in sequence, verify convergence."""
        ctx = _plan_ctx(
            allocations=[
                {"channel": "survival_fund", "policy_no": "P1", "amount": 1000},
                {"channel": "bonus", "policy_no": "P1", "amount": 500},
                {"channel": "policy_loan", "policy_no": "P1", "amount": 3000},
            ],
            channels=["survival_fund", "bonus", "policy_loan"],
            submitted=["survival_fund", "bonus"],
        )
        tc = ToolCall(
            id="final",
            name="submit_withdrawal",
            arguments={"operation_type": "loan"},
        )
        result = await tool.execute(tc, context=ctx)
        assert not result.is_error
        assert "待办理" not in str(result.content)
        delta = result.metadata.get("state_delta", {})
        assert set(delta["_submitted_channels"]) == {"survival_fund", "bonus", "policy_loan"}


class TestOperationTypeMapping:
    """Ensure operation_type -> channel -> flow_type mappings are stable."""

    @pytest.fixture
    def tool(self) -> SubmitWithdrawalTool:
        return SubmitWithdrawalTool()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "op_type,channel,expected_flow",
        [
            ("shengcunjin", "survival_fund", "shengcunjin-claim-E031"),
            ("bonus", "bonus", "bonus-claim"),
            ("loan", "policy_loan", "E027Flow"),
            ("partial", "partial_withdrawal", "U045Flow"),
            ("surrender", "surrender", "surrender"),
        ],
    )
    async def test_mapping_correct(
        self, tool: SubmitWithdrawalTool, op_type: str, channel: str, expected_flow: str,
    ) -> None:
        ctx = _plan_ctx(
            [{"channel": channel, "policy_no": "P1", "amount": 100}]
        )
        tc = ToolCall(
            id=f"map_{op_type}",
            name="submit_withdrawal",
            arguments={"operation_type": op_type},
        )
        result = await tool.execute(tc, context=ctx)
        assert not result.is_error
        ev = result.events[0]
        assert ev.payload["flow_type"] == expected_flow, (
            f"{op_type} -> {expected_flow}"
        )

    @pytest.mark.asyncio
    async def test_channel_name_as_operation_type_is_error(
        self, tool: SubmitWithdrawalTool,
    ) -> None:
        """Using channel name (survival_fund) instead of op_type (shengcunjin) must error."""
        tc = ToolCall(
            id="wrong_mapping",
            name="submit_withdrawal",
            arguments={"operation_type": "survival_fund"},
        )
        result = await tool.execute(tc, context=_plan_ctx([]))
        assert result.is_error is True
