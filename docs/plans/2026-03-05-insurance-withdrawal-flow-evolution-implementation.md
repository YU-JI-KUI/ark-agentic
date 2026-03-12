# Insurance Withdrawal Flow Evolution Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 为保险“领钱”场景落地轻量状态机与最小运行时门禁，确保 `clarify_need → withdraw_money → rewrite_plan` 的链路可控、可测、可审计。

**Architecture:** 采用“最小侵入”方案：不改现有 ReAct 主循环结构，不新增重型编排层。通过（1）保险域状态常量与转移函数、（2）工具结果 `metadata.state_delta` 标准化、（3）Runner 端状态转移校验与拒绝策略，实现流程确定性。技能文案同步为“显式前置条件 + 明确交接”。

**Tech Stack:** Python 3.12, pytest, Ark Agentic Runner/Tool/Skill framework

---

### Task 1: 建立保险领钱状态机契约（状态键 + 转移规则）

**Files:**
- Create: `src/ark_agentic/agents/insurance/flow_state.py`
- Create: `tests/agents/insurance/test_flow_state.py`

**Step 1: Write the failing test**

在 `tests/agents/insurance/test_flow_state.py` 新增：

```python
from ark_agentic.agents.insurance.flow_state import (
    WithdrawStage,
    can_transition,
    normalize_stage,
)


def test_normalize_stage_defaults_to_intent_received():
    assert normalize_stage(None) == WithdrawStage.INTENT_RECEIVED


def test_transition_clarify_to_options_ready_allowed():
    assert can_transition(WithdrawStage.NEED_CLARIFIED, WithdrawStage.OPTIONS_READY)


def test_transition_intent_to_rewrite_not_allowed():
    assert not can_transition(WithdrawStage.INTENT_RECEIVED, WithdrawStage.REWRITE_READY)
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/agents/insurance/test_flow_state.py -v`
Expected: FAIL（模块尚不存在）。

**Step 3: Write minimal implementation**

在 `src/ark_agentic/agents/insurance/flow_state.py` 实现：

```python
from enum import Enum


class WithdrawStage(str, Enum):
    INTENT_RECEIVED = "intent_received"
    NEED_CLARIFIED = "need_clarified"
    OPTIONS_READY = "options_ready"
    REWRITE_READY = "rewrite_ready"


def normalize_stage(raw: str | None) -> WithdrawStage:
    if not raw:
        return WithdrawStage.INTENT_RECEIVED
    try:
        return WithdrawStage(raw)
    except ValueError:
        return WithdrawStage.INTENT_RECEIVED


def can_transition(current: WithdrawStage, target: WithdrawStage) -> bool:
    if current == target:
        return True
    allowed = {
        WithdrawStage.INTENT_RECEIVED: {WithdrawStage.NEED_CLARIFIED, WithdrawStage.OPTIONS_READY},
        WithdrawStage.NEED_CLARIFIED: {WithdrawStage.OPTIONS_READY},
        WithdrawStage.OPTIONS_READY: {WithdrawStage.REWRITE_READY, WithdrawStage.OPTIONS_READY},
        WithdrawStage.REWRITE_READY: {WithdrawStage.REWRITE_READY, WithdrawStage.OPTIONS_READY},
    }
    return target in allowed[current]
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/agents/insurance/test_flow_state.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add tests/agents/insurance/test_flow_state.py src/ark_agentic/agents/insurance/flow_state.py
git commit -m "feat: add insurance withdrawal flow state contract"
```

---

### Task 2: 在规则引擎结果中写入 state_delta（流程可审计）

**Files:**
- Modify: `src/ark_agentic/agents/insurance/tools/rule_engine.py`
- Create: `tests/agents/insurance/test_rule_engine_state_delta.py`

**Step 1: Write the failing test**

在 `tests/agents/insurance/test_rule_engine_state_delta.py` 新增：

```python
import pytest

from ark_agentic.agents.insurance.tools.rule_engine import RuleEngineTool
from ark_agentic.core.types import ToolCall


class _FakeClient:
    async def call(self, api_code: str, user_id: str, **kwargs):
        return {
            "policyAssertList": [
                {
                    "policy_id": "POL001",
                    "product_name": "测试保单",
                    "product_type": "annuity",
                    "effective_date": "2021-01-01",
                    "survivalFundAmt": 10000,
                    "bounusAmt": 2000,
                    "loanAmt": 5000,
                    "policyRefundAmount": 8000,
                }
            ]
        }


@pytest.mark.asyncio
async def test_rule_engine_list_options_writes_state_delta():
    tool = RuleEngineTool(client=_FakeClient())
    tc = ToolCall(id="t1", name="rule_engine", arguments={"action": "list_options", "user_id": "U001", "amount": 12000})

    result = await tool.execute(tc)

    assert result.is_error is False
    assert result.metadata["state_delta"]["biz:withdraw.stage"] == "options_ready"
    assert result.metadata["state_delta"]["biz:withdraw.requested_amount"] == 12000
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/agents/insurance/test_rule_engine_state_delta.py -v`
Expected: FAIL（当前 metadata 未写入 state_delta）。

**Step 3: Write minimal implementation**

在 `src/ark_agentic/agents/insurance/tools/rule_engine.py` 的 `execute()` 中：

- `action == "list_options"` 成功分支返回 `AgentToolResult.json_result(..., metadata=...)`
- metadata 中加入：

```python
metadata = {
    "state_delta": {
        "biz:withdraw.stage": "options_ready",
        "biz:withdraw.requested_amount": amount,
        "biz:withdraw.last_action": "list_options",
    }
}
```

- `action == "calculate_detail"` 成功分支写入：

```python
"biz:withdraw.last_action": "calculate_detail"
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/agents/insurance/test_rule_engine_state_delta.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add tests/agents/insurance/test_rule_engine_state_delta.py src/ark_agentic/agents/insurance/tools/rule_engine.py
git commit -m "feat: emit withdrawal state delta from rule_engine"
```

---

### Task 3: 在 Runner 增加保险域最小状态转移门禁

**Files:**
- Modify: `src/ark_agentic/core/runner.py`
- Modify: `tests/core/test_runner.py`

**Step 1: Write the failing test**

在 `tests/core/test_runner.py` 新增（可复用现有 `_StateDeltaTool` 模式）：

```python
@pytest.mark.asyncio
async def test_runner_rejects_invalid_insurance_state_transition():
    from ark_agentic.core.types import AgentToolResult, ToolCall
    from ark_agentic.core.tools.base import AgentTool, ToolParameter

    class _InvalidTransitionTool(AgentTool):
        name = "invalid_transition_tool"
        description = "returns invalid stage jump"
        parameters = [ToolParameter(name="x", type="string", description="x")]

        async def execute(self, tool_call: ToolCall, context=None):
            return AgentToolResult.json_result(
                tool_call.id,
                {"ok": True},
                metadata={"state_delta": {"biz:withdraw.stage": "rewrite_ready"}},
            )

    responses = [
        AIMessage(content="", tool_calls=[{"name": "invalid_transition_tool", "args": {"x": "1"}, "id": "call_1"}]),
        AIMessage(content="done"),
    ]

    mock_llm = MockChatModel(responses=responses)
    registry = ToolRegistry()
    registry.register(_InvalidTransitionTool())

    runner = AgentRunner(
        llm=mock_llm,
        tool_registry=registry,
        session_manager=SessionManager(enable_persistence=False),
        config=RunnerConfig(max_turns=3, enable_streaming=False, auto_compact=False),
    )
    session = runner.session_manager.create_session_sync(state={"biz:agent_id": "insurance", "biz:withdraw.stage": "intent_received"})

    await runner.run(session.session_id, "test")
    state = runner.session_manager.get_session(session.session_id).state
    assert state["biz:withdraw.stage"] == "intent_received"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/core/test_runner.py::test_runner_rejects_invalid_insurance_state_transition -v`
Expected: FAIL（当前 Runner 会无条件 merge state_delta）。

**Step 3: Write minimal implementation**

在 `src/ark_agentic/core/runner.py`：

1. 新增私有方法 `_merge_state_delta_with_guard(session, state_delta)`：
   - 非 insurance 会话：保持现有浅合并行为。
   - insurance 会话（`session.state.get("biz:agent_id") == "insurance"`）时：
     - 读取当前 stage 与目标 stage。
     - 使用 `can_transition()` 判断是否允许。
     - 不允许时：记录 warning，拒绝 stage 更新，仅合并其他非 stage 字段。

2. 将原来直接 `session.update_state(state_delta)` 的位置改为调用上述方法。

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/core/test_runner.py::test_runner_rejects_invalid_insurance_state_transition -v`
Expected: PASS

**Step 5: Commit**

```bash
git add tests/core/test_runner.py src/ark_agentic/core/runner.py
git commit -m "feat: add insurance withdrawal state transition guard in runner"
```

---

### Task 4: 对齐技能文档前置条件与交接语义（clarify/withdraw/rewrite）

**Files:**
- Modify: `src/ark_agentic/agents/insurance/skills/clarify_need/SKILL.md`
- Modify: `src/ark_agentic/agents/insurance/skills/withdraw_money/SKILL.md`
- Modify: `src/ark_agentic/agents/insurance/skills/rewrite_plan/SKILL.md`

**Step 1: Write the failing test**

在 `tests/agents/insurance/test_skill_contracts.py` 新增：

```python
from pathlib import Path


def _read(p: str) -> str:
    return Path(p).read_text(encoding="utf-8")


def test_withdraw_skill_declares_options_ready_precondition():
    content = _read("src/ark_agentic/agents/insurance/skills/withdraw_money/SKILL.md")
    assert "options_ready" in content


def test_rewrite_skill_declares_rewrite_ready_precondition():
    content = _read("src/ark_agentic/agents/insurance/skills/rewrite_plan/SKILL.md")
    assert "rewrite_ready" in content
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/agents/insurance/test_skill_contracts.py -v`
Expected: FAIL（现有文档无显式状态前置约束）。

**Step 3: Write minimal implementation**

更新三份技能文档：

- `clarify_need/SKILL.md`：补充“金额确认后进入 `need_clarified`，触发 `rule_engine.list_options` 成功后进入 `options_ready`”。
- `withdraw_money/SKILL.md`：补充“执行前要求 `biz:withdraw.stage=options_ready`；完成推荐后可进入 `rewrite_ready`”。
- `rewrite_plan/SKILL.md`：补充“仅在 `rewrite_ready`（或已有历史方案）时触发”。

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/agents/insurance/test_skill_contracts.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add tests/agents/insurance/test_skill_contracts.py src/ark_agentic/agents/insurance/skills/clarify_need/SKILL.md src/ark_agentic/agents/insurance/skills/withdraw_money/SKILL.md src/ark_agentic/agents/insurance/skills/rewrite_plan/SKILL.md
git commit -m "docs: align insurance skill contracts with withdrawal state machine"
```

---

### Task 5: 补充保险领钱端到端流程测试（主路径 + 改写路径）

**Files:**
- Create: `tests/agents/insurance/test_withdrawal_flow_e2e.py`
- Verify: `src/ark_agentic/agents/insurance/agent.py`
- Verify: `src/ark_agentic/agents/insurance/tools/rule_engine.py`

**Step 1: Write the failing test**

在 `tests/agents/insurance/test_withdrawal_flow_e2e.py` 新增两个场景：

```python
@pytest.mark.asyncio
async def test_withdrawal_mainline_updates_stage_to_options_ready():
    ...
    assert state["biz:withdraw.stage"] == "options_ready"


@pytest.mark.asyncio
async def test_rewrite_after_options_ready_allowed():
    ...
    assert state["biz:withdraw.stage"] in {"options_ready", "rewrite_ready"}
```

> 说明：可使用 MockChatModel + 受控 tool_call 返回，避免真实 LLM/外部接口依赖。

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/agents/insurance/test_withdrawal_flow_e2e.py -v`
Expected: FAIL（新测试未落地或状态尚未完整接通）。

**Step 3: Write minimal implementation**

如有缺口，仅补最小代码：
- 在 `create_insurance_agent()` 创建 session 初始 state 时补默认 `biz:agent_id=insurance`（仅保险域）。
- 若 e2e 中出现 stage 丢失，补齐对应工具 metadata/state merge 逻辑。

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/agents/insurance/test_withdrawal_flow_e2e.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add tests/agents/insurance/test_withdrawal_flow_e2e.py src/ark_agentic/agents/insurance/agent.py src/ark_agentic/agents/insurance/tools/rule_engine.py src/ark_agentic/core/runner.py
git commit -m "test: add insurance withdrawal e2e flow coverage"
```

---

### Task 6: 全量回归与收尾校验

**Files:**
- Verify: `tests/agents/insurance/test_flow_state.py`
- Verify: `tests/agents/insurance/test_rule_engine_state_delta.py`
- Verify: `tests/agents/insurance/test_skill_contracts.py`
- Verify: `tests/agents/insurance/test_withdrawal_flow_e2e.py`
- Verify: `tests/core/test_runner.py`

**Step 1: Run focused insurance/core tests**

Run: `uv run pytest tests/agents/insurance/ tests/core/test_runner.py -v`
Expected: PASS

**Step 2: Run broader regression (if repo baseline allows)**

Run: `uv run pytest -v`
Expected: PASS（若出现历史遗留失败，记录为已知问题并附上不相关证明）。

**Step 3: Verify changed files and clean status**

Run: `git status`
Expected: 仅包含本计划涉及文件变更。

**Step 4: Final commit**

```bash
git add src/ark_agentic/agents/insurance/flow_state.py src/ark_agentic/agents/insurance/tools/rule_engine.py src/ark_agentic/core/runner.py src/ark_agentic/agents/insurance/skills/clarify_need/SKILL.md src/ark_agentic/agents/insurance/skills/withdraw_money/SKILL.md src/ark_agentic/agents/insurance/skills/rewrite_plan/SKILL.md tests/agents/insurance/test_flow_state.py tests/agents/insurance/test_rule_engine_state_delta.py tests/agents/insurance/test_skill_contracts.py tests/agents/insurance/test_withdrawal_flow_e2e.py tests/core/test_runner.py
git commit -m "feat: harden insurance withdrawal flow with lightweight state guard"
```
