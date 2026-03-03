# Securities Context Priority Design

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 统一 securities 工具参数优先级为 `user:* context > 裸 key context > tool args > 默认值`，并修复现有不一致逻辑与注释。

**Architecture:** 保持现有工具结构与 service adapter 不变，仅在各工具 `execute()` 内调整参数读取顺序，并修正文档注释。通过最小改动保证行为一致、低风险回归。

**Tech Stack:** Python, pytest, Ark Agentic tools framework

---

## 背景与问题

当前 `account_overview` 已采用“客户端 context 优先”的读取逻辑，但其他工具存在以下不一致：

1. 注释标明优先级与实际实现不一致（部分写成 tool args 优先）。
2. `user:*` 前缀键与裸 key 兼容读取未统一。
3. 同一业务在不同工具中的参数取值策略不一致，易导致行为漂移。

本设计目标是按最小改动统一规则，不做额外抽象重构。

## 统一优先级规则

对所有纳入范围的工具，统一采用：

`user:* context > 裸 key context > tool args > 默认值`

- `account_type`：`user:account_type` > `account_type(context裸key)` > `args.account_type` > `"normal"`
- `user_id`：`user:id` > `id(context裸key)` > `user:user_id` > `user_id(context裸key)` > `"U001"`

## 改动范围（A方案）

仅修改以下文件：

- `src/ark_agentic/agents/securities/tools/cash_assets.py`
- `src/ark_agentic/agents/securities/tools/etf_holdings.py`
- `src/ark_agentic/agents/securities/tools/hksc_holdings.py`
- `src/ark_agentic/agents/securities/tools/fund_holdings.py`
- `src/ark_agentic/agents/securities/tools/security_detail.py`

说明：
- 不改 `account_overview.py`（其优先级已作为基准）。
- 不改 `service_client.py` 与 `param_mapping.py`（避免扩大影响面）。
- 不新增公共 helper（避免本轮引入重构风险）。

## 实施步骤（任务级）

### Task 1: cash_assets 优先级对齐

**Files:**
- Modify: `src/ark_agentic/agents/securities/tools/cash_assets.py`

**Step 1:** 将 `account_type` 的取值顺序改为 context 优先（`_get_context_value(..., args.get("account_type"))` 形式）。
**Step 2:** `user_id` 统一先取 `id` 再回退 `user_id`。
**Step 3:** 修正文档注释与行内优先级注释。
**Step 4:** 运行相关测试。

### Task 2: etf_holdings 优先级对齐

**Files:**
- Modify: `src/ark_agentic/agents/securities/tools/etf_holdings.py`

**Step 1:** 调整 `account_type` 读取顺序为 context 优先。
**Step 2:** 调整 `user_id` 读取顺序。
**Step 3:** 修正文档注释与行内优先级注释。
**Step 4:** 运行相关测试。

### Task 3: hksc_holdings 优先级对齐

**Files:**
- Modify: `src/ark_agentic/agents/securities/tools/hksc_holdings.py`

**Step 1:** 调整 `account_type` 读取顺序为 context 优先。
**Step 2:** 调整 `user_id` 读取顺序。
**Step 3:** 修正文档注释与行内优先级注释。
**Step 4:** 运行相关测试。

### Task 4: fund_holdings 优先级对齐

**Files:**
- Modify: `src/ark_agentic/agents/securities/tools/fund_holdings.py`

**Step 1:** 调整 `account_type` 读取顺序为 context 优先。
**Step 2:** 调整 `user_id` 读取顺序。
**Step 3:** 修正文档注释与行内优先级注释。
**Step 4:** 运行相关测试。

### Task 5: security_detail 优先级对齐

**Files:**
- Modify: `src/ark_agentic/agents/securities/tools/security_detail.py`

**Step 1:** 保持 `security_code` 参数读取不变。
**Step 2:** 调整 `account_type` 与 `user_id` 为 context 优先。
**Step 3:** 修正文档注释与行内优先级注释。
**Step 4:** 运行相关测试。

### Task 6: 测试补强与回归

**Files:**
- Modify: `tests/test_context_injection.py`
- Verify: `tests/test_static_index_render_contract.py`
- Verify: `tests/core/test_runner.py`

**Step 1:** 增加至少一个“args 与 context 冲突”测试用例，断言 context 胜出。
**Step 2:** 增加至少一个“user:* 与裸 key 冲突”测试用例，断言 `user:*` 胜出。
**Step 3:** 运行测试命令：
- `pytest -q tests/test_context_injection.py`
- `pytest -q tests/test_static_index_render_contract.py`
- `pytest -q tests/core/test_runner.py::test_input_context_seed_only tests/core/test_runner.py::test_temp_state_stripped_after_run`

**Step 4:** 确认全部通过后再提交。

## 风险与回滚

- 风险：mock 场景中 account_type 分支切换可能受读取顺序影响。
- 控制：通过冲突用例验证“context 覆盖 args”行为。
- 回滚：仅影响工具层参数读取，可按文件粒度回退。

## 验收标准

1. 目标 5 个工具中不再出现“tool args 优先于 context”的实现。
2. 注释与实现一致，统一为：`user:* context > 裸 key context > tool args > 默认值`。
3. 指定测试命令全部通过。
