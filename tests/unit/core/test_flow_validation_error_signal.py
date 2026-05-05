"""Smoke tests for the simplified flow framework.

Covers:
1. 字段缺失 → in_progress（不再有阻断/blocked 概念）。
2. Pydantic 校验失败 → in_progress + FieldStatus.error。
3. 已落盘 stage_* 视为 completed，不二次校验。
4. before_tool_stage_guard 拦截越级调用下游 stage 的工具。
5. flat 持久化 / resume 形状一致。
"""

from __future__ import annotations

import json
from typing import Any
from pathlib import Path

import pytest
from pydantic import BaseModel, Field

from ark_agentic.core.flow.base_evaluator import (
    BaseFlowEvaluator,
    FieldDefinition,
    FieldSource,
    FlowEvaluatorRegistry,
    StageDefinition,
)
from ark_agentic.core.flow.callbacks import FlowCallbacks, _build_evaluation_message
from ark_agentic.core.callbacks import CallbackContext, HookAction
from ark_agentic.core.types import (
    AgentToolResult,
    SessionEntry,
    ToolCall,
    ToolLoopAction,
    ToolResultType,
)


def _parse_flow_evaluation_json(text: str) -> dict[str, Any]:
    """从 ``<flow_evaluation>`` 内嵌的 ```json 围栏取出对象。"""
    start = text.index("```json") + len("```json")
    end = text.index("```", start)
    return json.loads(text[start:end].strip())


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
                tools=["customer_info"],
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
                tools=["render_a2ui"],
                fields={
                    "amount": FieldDefinition(description="领取金额"),
                },
            ),
        ]


# ── Scenario 1: missing state key → in_progress ──────────────────────────────


def test_evaluate_missing_state_key_is_in_progress() -> None:
    ev = _Evaluator()
    flow_ctx: dict[str, Any] = {"flow_id": "test123"}
    state: dict[str, Any] = {}

    result = ev.evaluate(flow_ctx, state)

    assert not result.is_done
    assert result.current_stage is not None
    assert result.current_stage.id == "identity_verify"
    in_progress = [e for e in result.stage_evaluations if e.status == "in_progress"]
    assert len(in_progress) == 1
    assert in_progress[0].fields is not None
    assert all(fs.status == "missing" for fs in in_progress[0].fields.values())
    assert "stage_identity_verify" not in flow_ctx
    assert flow_ctx["current_stage"] == "identity_verify"
    assert result.state_delta["_flow_context.current_stage"] == "identity_verify"


# ── Scenario 2: validation failure → in_progress + field error ───────────────


def test_evaluate_validation_failure_marks_field_error() -> None:
    ev = _Evaluator()
    flow_ctx: dict[str, Any] = {"flow_id": "test123"}
    state: dict[str, Any] = {"identity": {"verified": "not-a-bool", "customer_id": "C123"}}

    result = ev.evaluate(flow_ctx, state)

    assert not result.is_done
    assert result.current_stage is not None
    assert result.current_stage.id == "identity_verify"
    in_progress = [e for e in result.stage_evaluations if e.status == "in_progress"]
    assert len(in_progress) == 1
    assert in_progress[0].fields is not None
    error_fields = {k: v for k, v in in_progress[0].fields.items() if v.status == "error"}
    assert error_fields, "校验失败时至少有一个字段应被标记为 error"
    assert "stage_identity_verify" not in flow_ctx


def test_build_evaluation_message_renders_invalid_stage() -> None:
    ev = _Evaluator()
    flow_ctx: dict[str, Any] = {"flow_id": "test123"}
    state: dict[str, Any] = {"identity": {"verified": "not-a-bool", "customer_id": "C123"}}

    result = ev.evaluate(flow_ctx, state)
    text = _build_evaluation_message(result)
    assert "<flow_evaluation>" in text
    assert "</flow_evaluation>" in text
    assert '"result": "invalid"' in text
    assert "identity_verify" in text


# ── Scenario 3: already committed → completed without re-validation ──────────


def test_evaluate_valid_tool_data_auto_commits() -> None:
    ev = _Evaluator()
    flow_ctx: dict[str, Any] = {"flow_id": "test123"}
    state: dict[str, Any] = {"identity": {"verified": True, "customer_id": "C123"}}

    result = ev.evaluate(flow_ctx, state)

    assert flow_ctx["stage_identity_verify"] == {"verified": True, "customer_id": "C123"}
    assert flow_ctx["current_stage"] == "plan_confirm"
    assert not result.is_done
    assert result.current_stage is not None
    assert result.current_stage.id == "plan_confirm"


def test_committed_stage_skips_revalidation() -> None:
    """有 stage_* dict 即视为 completed，不再二次跑 schema 校验。"""
    ev = _Evaluator()
    flow_ctx: dict[str, Any] = {
        "flow_id": "test123",
        "stage_identity_verify": {"verified": True},  # customer_id 缺失但不再校验
    }
    state: dict[str, Any] = {}

    result = ev.evaluate(flow_ctx, state)

    completed = [e for e in result.stage_evaluations if e.status == "completed"]
    assert any(e.id == "identity_verify" for e in completed)
    # 当前阶段应推进到 plan_confirm（in_progress）
    assert result.current_stage is not None
    assert result.current_stage.id == "plan_confirm"
    assert flow_ctx["current_stage"] == "plan_confirm"


def test_build_evaluation_message_clean_when_no_errors() -> None:
    ev = _Evaluator()
    flow_ctx: dict[str, Any] = {"flow_id": "test123"}
    state: dict[str, Any] = {}
    result = ev.evaluate(flow_ctx, state)

    text = _build_evaluation_message(result)
    assert "<flow_evaluation>" in text
    assert '"result": "incomplete"' in text
    assert '"result": "blocked"' not in text
    assert "identity_verify" in text
    # 缺失项均有 state_key（工具侧抽取），JSON hint 中不应引导 collect_user_fields（通用约定里会提到该工具名）
    payload = _parse_flow_evaluation_json(text)
    for entry in payload["current_stage"]["outstanding_fields"].values():
        assert "collect_user_fields" not in str(entry.get("hint", ""))
    assert "stages_overview" not in text
    assert "outstanding_fields" in text
    # 工具侧缺失须透出 FieldStatus.error 作为 hint，避免只剩裸 status
    assert "hint" in text
    assert "state_key" in text


def test_build_evaluation_message_collect_hint_when_user_field_missing() -> None:
    """无 state_key 的字段缺失时，在 outstanding_fields.*.hint 中提示 collect_user_fields。"""
    ev = _Evaluator()
    flow_ctx: dict[str, Any] = {
        "flow_id": "test123",
        "stage_identity_verify": {"verified": True, "customer_id": "C1"},
    }
    state: dict[str, Any] = {}
    result = ev.evaluate(flow_ctx, state)

    assert result.current_stage is not None
    assert result.current_stage.id == "plan_confirm"
    text = _build_evaluation_message(result)
    assert "<flow_evaluation>" in text
    assert "outstanding_fields" in text
    assert "stages_overview" not in text
    assert "collect_user_fields" in text
    assert "请向用户确认后调用 `collect_user_fields` 提交该字段" in text


def test_build_evaluation_message_includes_protocol_when_not_done() -> None:
    ev = _Evaluator()
    flow_ctx: dict[str, Any] = {"flow_id": "f1", "skill_name": "test_flow"}
    state: dict[str, Any] = {}
    result = ev.evaluate(flow_ctx, state)
    assert not result.is_done
    text = _build_evaluation_message(result)
    assert "流程评估约定" in text
    assert "阶段守卫" in text


def test_build_evaluation_message_completed_minimal() -> None:
    ev = _Evaluator()
    flow_ctx: dict[str, Any] = {
        "flow_id": "test123",
        "stage_identity_verify": {"verified": True, "customer_id": "C1"},
        "stage_plan_confirm": {"amount": 100.0},
    }
    state: dict[str, Any] = {}
    result = ev.evaluate(flow_ctx, state)
    assert result.is_done

    text = _build_evaluation_message(result)
    assert "<flow_evaluation>" in text
    assert "流程评估约定" not in text
    assert '"flow_status": "completed"' in text
    assert "stages_overview" not in text
    assert "current_stage" not in text
    payload = _parse_flow_evaluation_json(text)
    assert payload["flow_status"] == "completed"
    assert payload["process_name"] == "当前流程执行状态评估"


def test_field_source_is_field_definition_alias() -> None:
    assert FieldSource is FieldDefinition
    fd = FieldSource(description="test field", state_key="some_key")
    assert fd.description == "test field"
    assert fd.state_key == "some_key"


def test_completed_stages_backward_compat() -> None:
    ev = _Evaluator()
    flow_ctx: dict[str, Any] = {"flow_id": "test123"}
    state: dict[str, Any] = {}
    result = ev.evaluate(flow_ctx, state)

    assert len(result.completed_stages) == len(result.stage_evaluations)
    assert result.completed_stages[0]["status"] == "incomplete"


# ── Scenario 4: before_tool_stage_guard ──────────────────────────────────────


def _make_ctx_with_flow(flow_ctx: dict[str, Any]) -> CallbackContext:
    state: dict[str, Any] = {"_flow_context": flow_ctx}
    session = SessionEntry.create(model="m", provider="p", state=state)
    return CallbackContext(user_input="", input_context={}, session=session)


@pytest.mark.asyncio
async def test_stage_guard_blocks_future_stage_tool(tmp_path: Path) -> None:
    ev = _Evaluator()
    FlowEvaluatorRegistry.register(ev)

    fc = FlowCallbacks(sessions_dir=tmp_path)
    flow_ctx = {
        "flow_id": "f1",
        "skill_name": "test_flow",
        "current_stage": "identity_verify",
    }
    ctx = _make_ctx_with_flow(flow_ctx)
    tool_calls = [
        ToolCall(id="tc-future", name="render_a2ui", arguments={}),
    ]

    result = await fc.before_tool_stage_guard(ctx, turn=1, tool_calls=tool_calls)

    assert result is not None
    assert result.action == HookAction.OVERRIDE
    assert result.tool_results is not None
    assert len(result.tool_results) == 1
    tr = result.tool_results[0]
    assert tr.loop_action == ToolLoopAction.STOP
    assert tr.result_type == ToolResultType.TEXT
    assert "尚未完成" in tr.content


@pytest.mark.asyncio
async def test_stage_guard_passes_current_and_generic_tools(tmp_path: Path) -> None:
    ev = _Evaluator()
    FlowEvaluatorRegistry.register(ev)

    fc = FlowCallbacks(sessions_dir=tmp_path)
    flow_ctx = {
        "flow_id": "f1",
        "skill_name": "test_flow",
        "current_stage": "identity_verify",
    }
    ctx = _make_ctx_with_flow(flow_ctx)
    tool_calls = [
        ToolCall(id="tc-1", name="customer_info", arguments={}),  # 当前 stage 工具
        ToolCall(id="tc-2", name="collect_user_fields", arguments={}),  # 通用工具
    ]

    result = await fc.before_tool_stage_guard(ctx, turn=1, tool_calls=tool_calls)

    assert result is None  # 全部放行


@pytest.mark.asyncio
async def test_stage_guard_skips_when_completed(tmp_path: Path) -> None:
    ev = _Evaluator()
    FlowEvaluatorRegistry.register(ev)

    fc = FlowCallbacks(sessions_dir=tmp_path)
    flow_ctx = {
        "flow_id": "f1",
        "skill_name": "test_flow",
        "current_stage": "__completed__",
    }
    ctx = _make_ctx_with_flow(flow_ctx)
    tool_calls = [ToolCall(id="tc-x", name="render_a2ui", arguments={})]

    result = await fc.before_tool_stage_guard(ctx, turn=1, tool_calls=tool_calls)

    assert result is None


# ── Scenario 5: flat persist / resume shape ──────────────────────────────────


def test_persistable_context_is_flat_and_strips_user_inputs() -> None:
    ev = _Evaluator()
    flow_ctx = {
        "flow_id": "f1",
        "skill_name": "test_flow",
        "current_stage": "plan_confirm",
        "stage_identity_verify": {"verified": True, "customer_id": "C123"},
        "stage_identity_verify_delta": {"identity": {"verified": True}},
        "_user_input_plan_confirm": {"amount": 100.0},
        "checkpoints": [],
    }

    snapshot = ev.get_persistable_context(flow_ctx)

    assert snapshot["flow_id"] == "f1"
    assert snapshot["skill_name"] == "test_flow"
    assert snapshot["current_stage"] == "plan_confirm"
    assert "stage_identity_verify" in snapshot
    assert "stage_identity_verify_delta" in snapshot
    assert "_user_input_plan_confirm" not in snapshot


def test_iter_delta_state_walks_flat_context() -> None:
    ev = _Evaluator()
    flow_ctx = {
        "stage_a_delta": {"k1": "v1"},
        "stage_b_delta": {"k2": "v2"},
        "stage_a": {"data": 1},  # 非 _delta 不应产出
    }
    pairs = list(ev.iter_delta_state(flow_ctx))
    assert ("k1", "v1") in pairs
    assert ("k2", "v2") in pairs
    assert all(p[0] != "data" for p in pairs)
