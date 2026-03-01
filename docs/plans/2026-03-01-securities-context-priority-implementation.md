# Securities Context Priority Unification Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 让 securities 相关工具统一使用 `user:* context > 裸 key context > tool args > 默认值` 的参数优先级，并通过测试锁定该行为。

**Architecture:** 采用最小改动策略，不重构共享模块，不改 adapter 协议。仅在工具 `execute()` 内统一取值顺序，并修正注释文案。通过 `tests/test_context_injection.py` 增加冲突场景测试，确保优先级不会回归。

**Tech Stack:** Python 3.12, pytest, Ark Agentic tool framework

---

### Task 1: 为 cash_assets 添加“context 优先于 args”失败用例

**Files:**
- Modify: `tests/test_context_injection.py`
- Verify target: `src/ark_agentic/agents/securities/tools/cash_assets.py`

**Step 1: Write the failing test**

在 `tests/test_context_injection.py` 新增：

```python
@pytest.mark.asyncio
async def test_cash_assets_context_priority_over_args():
    from ark_agentic.agents.securities.tools.cash_assets import CashAssetsTool

    tool = CashAssetsTool()
    tool_call = ToolCall(
        id="test_cash_priority",
        name="cash_assets",
        arguments={"account_type": "normal"},
    )

    context = {
        "account_type": "normal",
        "user:account_type": "margin",
        "user:id": "U001",
    }

    result = await tool.execute(tool_call, context=context)
    extracted = extract_account_overview(result.content)

    assert extracted.get("net_assets") is not None
```

**Step 2: Run test to verify it fails**

Run:
`pytest tests/test_context_injection.py::test_cash_assets_context_priority_over_args -v`

Expected: FAIL（当前逻辑会优先使用 args.account_type）。

**Step 3: Write minimal implementation**

在 `src/ark_agentic/agents/securities/tools/cash_assets.py` 将 account_type 读取改为：

```python
account_type = _get_context_value(
    context, "account_type", args.get("account_type") or "normal"
)
```

并保持 user_id 按 `id -> user_id -> 默认值`。

**Step 4: Run test to verify it passes**

Run:
`pytest tests/test_context_injection.py::test_cash_assets_context_priority_over_args -v`

Expected: PASS

**Step 5: Commit**

```bash
git add tests/test_context_injection.py src/ark_agentic/agents/securities/tools/cash_assets.py
git commit -m "fix: prioritize context over args in cash_assets"
```

---

### Task 2: 对齐 etf_holdings 优先级与注释

**Files:**
- Modify: `src/ark_agentic/agents/securities/tools/etf_holdings.py`
- Test: `tests/test_context_injection.py`

**Step 1: Write the failing test**

在 `tests/test_context_injection.py` 新增：

```python
@pytest.mark.asyncio
async def test_etf_holdings_prefers_user_prefixed_context():
    from ark_agentic.agents.securities.tools.etf_holdings import ETFHoldingsTool

    tool = ETFHoldingsTool()
    tool_call = ToolCall(
        id="test_etf_priority",
        name="etf_holdings",
        arguments={"account_type": "normal"},
    )
    context = {
        "account_type": "normal",
        "user:account_type": "margin",
        "user:id": "U001",
    }

    result = await tool.execute(tool_call, context=context)
    assert result.error is None
```

**Step 2: Run test to verify it fails**

Run:
`pytest tests/test_context_injection.py::test_etf_holdings_prefers_user_prefixed_context -v`

Expected: FAIL（若仍是 args 优先）。

**Step 3: Write minimal implementation**

在 `src/ark_agentic/agents/securities/tools/etf_holdings.py`：
- 将 account_type 从 `args.get(...) or _get_context_value(...)` 改为 context 优先。
- 将注释更新为：
  `参数优先级：user:* context > 裸 key context > tool args > 默认值`

**Step 4: Run test to verify it passes**

Run:
`pytest tests/test_context_injection.py::test_etf_holdings_prefers_user_prefixed_context -v`

Expected: PASS

**Step 5: Commit**

```bash
git add tests/test_context_injection.py src/ark_agentic/agents/securities/tools/etf_holdings.py
git commit -m "fix: align etf_holdings context precedence"
```

---

### Task 3: 对齐 hksc_holdings 优先级与注释

**Files:**
- Modify: `src/ark_agentic/agents/securities/tools/hksc_holdings.py`
- Test: `tests/test_context_injection.py`

**Step 1: Write the failing test**

新增：

```python
@pytest.mark.asyncio
async def test_hksc_holdings_context_priority_over_args():
    from ark_agentic.agents.securities.tools.hksc_holdings import HKSCHoldingsTool

    tool = HKSCHoldingsTool()
    tool_call = ToolCall(
        id="test_hksc_priority",
        name="hksc_holdings",
        arguments={"account_type": "normal"},
    )
    context = {"user:account_type": "margin", "user:id": "U001"}

    result = await tool.execute(tool_call, context=context)
    assert result.error is None
```

**Step 2: Run test to verify it fails**

Run:
`pytest tests/test_context_injection.py::test_hksc_holdings_context_priority_over_args -v`

Expected: FAIL

**Step 3: Write minimal implementation**

在 `src/ark_agentic/agents/securities/tools/hksc_holdings.py` 将 account_type 改成 context 优先。

**Step 4: Run test to verify it passes**

Run:
`pytest tests/test_context_injection.py::test_hksc_holdings_context_priority_over_args -v`

Expected: PASS

**Step 5: Commit**

```bash
git add tests/test_context_injection.py src/ark_agentic/agents/securities/tools/hksc_holdings.py
git commit -m "fix: align hksc_holdings context precedence"
```

---

### Task 4: 对齐 fund_holdings 优先级与注释

**Files:**
- Modify: `src/ark_agentic/agents/securities/tools/fund_holdings.py`
- Test: `tests/test_context_injection.py`

**Step 1: Write the failing test**

新增：

```python
@pytest.mark.asyncio
async def test_fund_holdings_context_priority_over_args():
    from ark_agentic.agents.securities.tools.fund_holdings import FundHoldingsTool

    tool = FundHoldingsTool()
    tool_call = ToolCall(
        id="test_fund_priority",
        name="fund_holdings",
        arguments={"account_type": "normal"},
    )
    context = {"user:account_type": "margin", "user:id": "U001"}

    result = await tool.execute(tool_call, context=context)
    assert result.error is None
```

**Step 2: Run test to verify it fails**

Run:
`pytest tests/test_context_injection.py::test_fund_holdings_context_priority_over_args -v`

Expected: FAIL

**Step 3: Write minimal implementation**

在 `src/ark_agentic/agents/securities/tools/fund_holdings.py`：

```python
account_type = _get_context_value(
    context, "account_type", args.get("account_type") or "normal"
)
```

**Step 4: Run test to verify it passes**

Run:
`pytest tests/test_context_injection.py::test_fund_holdings_context_priority_over_args -v`

Expected: PASS

**Step 5: Commit**

```bash
git add tests/test_context_injection.py src/ark_agentic/agents/securities/tools/fund_holdings.py
git commit -m "fix: align fund_holdings context precedence"
```

---

### Task 5: 对齐 security_detail 优先级与注释

**Files:**
- Modify: `src/ark_agentic/agents/securities/tools/security_detail.py`
- Test: `tests/test_context_injection.py`

**Step 1: Write the failing test**

新增：

```python
@pytest.mark.asyncio
async def test_security_detail_context_priority_over_args():
    from ark_agentic.agents.securities.tools.security_detail import SecurityDetailTool

    tool = SecurityDetailTool()
    tool_call = ToolCall(
        id="test_security_detail_priority",
        name="security_detail",
        arguments={"security_code": "510300", "account_type": "normal"},
    )
    context = {"user:account_type": "margin", "user:id": "U001"}

    result = await tool.execute(tool_call, context=context)
    assert result.error is None
```

**Step 2: Run test to verify it fails**

Run:
`pytest tests/test_context_injection.py::test_security_detail_context_priority_over_args -v`

Expected: FAIL

**Step 3: Write minimal implementation**

在 `src/ark_agentic/agents/securities/tools/security_detail.py`：
- 保持 `security_code` 从 args 读取。
- 仅将 `account_type` 改为 context 优先。

**Step 4: Run test to verify it passes**

Run:
`pytest tests/test_context_injection.py::test_security_detail_context_priority_over_args -v`

Expected: PASS

**Step 5: Commit**

```bash
git add tests/test_context_injection.py src/ark_agentic/agents/securities/tools/security_detail.py
git commit -m "fix: align security_detail context precedence"
```

---

### Task 6: 全量回归与最终提交

**Files:**
- Verify: `tests/test_context_injection.py`
- Verify: `tests/test_static_index_render_contract.py`
- Verify: `tests/core/test_runner.py`

**Step 1: Run context tests**

Run:
`pytest -q tests/test_context_injection.py`

Expected: PASS（0 failed）

**Step 2: Run card rendering contract tests**

Run:
`pytest -q tests/test_static_index_render_contract.py`

Expected: PASS（0 failed）

**Step 3: Run runner context regression tests**

Run:
`pytest -q tests/core/test_runner.py::test_input_context_seed_only tests/core/test_runner.py::test_temp_state_stripped_after_run`

Expected: PASS（0 failed）

**Step 4: Final commit**

```bash
git add \
  src/ark_agentic/agents/securities/tools/cash_assets.py \
  src/ark_agentic/agents/securities/tools/etf_holdings.py \
  src/ark_agentic/agents/securities/tools/hksc_holdings.py \
  src/ark_agentic/agents/securities/tools/fund_holdings.py \
  src/ark_agentic/agents/securities/tools/security_detail.py \
  tests/test_context_injection.py

git commit -m "fix: unify securities tool context precedence"
```

---

## 实施注意事项

- 保持 YAGNI：不要在本轮提取公共 helper。
- 保持 DRY（在单文件范围内）：只改参数取值行与注释，不做额外重构。
- 所有完成声明都要附带最新测试输出（遵循 @verification-before-completion）。
