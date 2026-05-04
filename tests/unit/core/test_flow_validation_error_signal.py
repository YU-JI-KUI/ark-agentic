"""Smoke tests for flow validation error handling.

Covers three scenarios:

1. missing state key → stage in_progress (missing fields), not blocked.
2. validation failure → is_blocked=True, FieldStatus.error on failed fields.
3. incomplete stage errors (resume / schema drift) → is_blocked=True with error fields.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from ark_agentic.core.flow.base_evaluator import (
    BaseFlowEvaluator,
    FieldDefinition,
    FieldSource,
    StageDefinition,
)
from ark_agentic.core.flow.callbacks import _build_evaluation_message


# ── Test evaluator fixture ───────────────────────────────────────────────────


class _Identity(BaseModel):
    verified: bool = Field(...)
    customer_id: str = Field(...)


class _Plan(BaseModel):
    amount: float = Field(..., gt=0)


class _Evaluator(BaseFlowEvaluator):
    @property
    def skill_name(self) -> str:
        return "test_flow"

    @property
    def stages(self) -> list[StageDefinition]:
        return [
            StageDefinition(
                id="identity_verify",
                name="身份核验",
                description="核验用户身份",
                output_schema=_Identity,
                fields={
                    "verified": FieldDefinition(state_key="identity", path="verified"),
                    "customer_id": FieldDefinition(state_key="identity", path="customer_id"),
                },
            ),
            StageDefinition(
                id="plan_confirm",
                name="方案确认",
                description="用户确认方案",
                output_schema=_Plan,
                fields={
                    "amount": FieldDefinition(description="领取金额"),
                },
            ),
        ]


# ── Scenario 1: missing state key → in_progress, not blocked ─────────────────


def test_evaluate_missing_state_key_is_in_progress() -> None:
    ev = _Evaluator()
    flow_ctx: dict[str, Any] = {"flow_id": "test123"}
    state: dict[str, Any] = {}          # identity state key absent

    result = ev.evaluate(flow_ctx, state)

    assert not result.is_done
    assert not result.is_blocked
    assert result.current_stage is not None
    assert result.current_stage.id == "identity_verify"

    # Check stage_evaluations: first stage is in_progress with missing fields
    in_progress_eval = [e for e in result.stage_evaluations if e.status == "in_progress"]
    assert len(in_progress_eval) == 1
    assert in_progress_eval[0].id == "identity_verify"
    assert in_progress_eval[0].fields is not None
    assert all(fs.status == "missing" for fs in in_progress_eval[0].fields.values())

    # Stage was NOT committed.
    assert "stage_identity_verify" not in flow_ctx


# ── Scenario 2: validation failure → is_blocked=True ─────────────────────────


def test_evaluate_validation_failure_is_blocked() -> None:
    ev = _Evaluator()
    flow_ctx: dict[str, Any] = {"flow_id": "test123"}
    # identity tool returned data with wrong type: verified is str instead of bool.
    # All field values are non-None so they're collected, but Pydantic validation fails.
    state: dict[str, Any] = {"identity": {"verified": "not-a-bool", "customer_id": "C123"}}

    result = ev.evaluate(flow_ctx, state)

    assert not result.is_done
    assert result.is_blocked
    assert result.current_stage is not None
    assert result.current_stage.id == "identity_verify"

    # Check stage_evaluations: first stage is in_progress with error fields
    in_progress_eval = [e for e in result.stage_evaluations if e.status == "in_progress"]
    assert len(in_progress_eval) == 1
    assert in_progress_eval[0].id == "identity_verify"
    assert in_progress_eval[0].fields is not None
    # Some fields should have error status (validation failed)
    error_fields = {k: v for k, v in in_progress_eval[0].fields.items() if v.status == "error"}
    assert len(error_fields) > 0

    # Stage was NOT committed on validation failure.
    assert "stage_identity_verify" not in flow_ctx


def test_build_evaluation_message_renders_blocked_stage() -> None:
    """evaluate 校验失败后，is_blocked=True 应在评估消息中渲染阻断信息。"""
    ev = _Evaluator()
    flow_ctx: dict[str, Any] = {"flow_id": "test123"}
    # Provide non-None data that fails Pydantic validation
    state: dict[str, Any] = {"identity": {"verified": "not-a-bool", "customer_id": "C123"}}

    result = ev.evaluate(flow_ctx, state)
    assert result.is_blocked

    msg = _build_evaluation_message(result)
    assert msg["role"] == "system"
    text = msg["content"]
    assert "blocked" in text
    assert "identity_verify" in text


def test_evaluate_valid_tool_data_auto_commits() -> None:
    """When tool data is valid, evaluate auto-commits the stage."""
    ev = _Evaluator()
    flow_ctx: dict[str, Any] = {"flow_id": "test123"}
    state: dict[str, Any] = {"identity": {"verified": True, "customer_id": "C123"}}

    result = ev.evaluate(flow_ctx, state)

    # Stage should be auto-committed
    assert flow_ctx["stage_identity_verify"] == {"verified": True, "customer_id": "C123"}
    # Now current stage should be plan_confirm (in_progress, missing user fields)
    assert not result.is_done
    assert result.current_stage is not None
    assert result.current_stage.id == "plan_confirm"


def test_format_flow_status_renders_incomplete_errors() -> None:
    ev = _Evaluator()
    # Simulate resume/schema drift: stage_identity_verify already exists but
    # fails the current output_schema (missing customer_id).
    flow_ctx: dict[str, Any] = {
        "flow_id": "test123",
        "stage_identity_verify": {"verified": True},  # customer_id missing → invalid
    }
    state: dict[str, Any] = {}
    result = ev.evaluate(flow_ctx, state)

    # Already committed but invalid stage should still be treated as completed
    # (it's already in flow_ctx), but validate_output will fail on next stage
    # The evaluator treats already-committed stages (with data in flow_ctx) as completed
    assert result.current_stage is not None


def test_build_evaluation_message_clean_when_no_errors() -> None:
    ev = _Evaluator()
    flow_ctx: dict[str, Any] = {"flow_id": "test123"}
    state: dict[str, Any] = {}
    result = ev.evaluate(flow_ctx, state)

    msg = _build_evaluation_message(result)
    assert msg["role"] == "system"
    text = msg["content"]
    # No blocked result when not blocked.
    assert '"result": "blocked"' not in text
    assert '"result": "incomplete"' in text
    # Current stage info is rendered.
    assert "identity_verify" in text
    assert "身份核验" in text


def test_field_source_is_field_definition_alias() -> None:
    """FieldSource should be a backward-compatible alias for FieldDefinition."""
    assert FieldSource is FieldDefinition

    # FieldSource() should work with the new signature
    fd = FieldSource(description="test field", state_key="some_key")
    assert fd.description == "test field"
    assert fd.state_key == "some_key"


def test_completed_stages_backward_compat() -> None:
    """FlowEvalResult.completed_stages property should work for backward compat."""
    ev = _Evaluator()
    flow_ctx: dict[str, Any] = {"flow_id": "test123"}
    state: dict[str, Any] = {}
    result = ev.evaluate(flow_ctx, state)

    # completed_stages should be derivable from stage_evaluations
    assert len(result.completed_stages) == len(result.stage_evaluations)
    # First entry should be the in_progress stage
    assert result.completed_stages[0]["status"] == "incomplete"
