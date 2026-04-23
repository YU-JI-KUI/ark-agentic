---
title: Flow 框架 Refactor 清单
status: planning
last_updated: 2026-04-20
---

# Flow 框架 Refactor 清单

> 本文档梳理 Flow 框架当前的技术债，包含 **已完成的清理** 和 **剩余待重构项**。
> 优先级按 P0 > P1 > P2 > P3 递减。P0/P1 建议近期推进，P2/P3 酌情。

---

## 背景

Flow 框架近期经历了一次大的架构转型：`FlowEvaluator` 和 `CommitFlowStageTool` 从 LLM 可调用工具下沉为框架层 Hook，改由 `before_model` / `after_tool` 自动驱动。LLM 只需面对 `CollectUserFieldsTool` / `RollbackFlowStageTool` / `ResumeTaskTool` 三个轻量工具。

这次转型暴露出一些命名、注册、职责边界方面的技术债。本文列出的项即为后续需要逐步消化的内容。

---

## 一、已完成（上一轮清理）

| ID | 内容 | 影响文件 |
|---|---|---|
| ✅ P0-a | `FlowEvaluatorRegistry.register(evaluator, namespace=...)` 支持命名空间别名，兼顾 `skill_name` 短名查询和 `"{namespace}.{skill_name}"` 全名查询 | `core/flow/base_evaluator.py` |
| ✅ P0-b | 简化 `before_model_flow_eval` 和 `_enrich_skills_with_stage_reference` 的 evaluator 查找逻辑，统一走 `FlowEvaluatorRegistry.get(skill.id)` | `core/flow/callbacks.py`、`core/runner.py` |
| ✅ P1 | `resume_task` discard 分支显式清空 `_flow_context` 并把 `_pending_checked_<skill>` 置 `False`，修复"discard 后再次触发同一流程，pending 检测被跳过"的副作用 | `core/tools/resume_task.py` |
| ✅ P2 | 抽出 `core/state_utils.py`，合并 runner 和 callbacks 两份 dot-path `_apply_state_delta` 实现 | `core/state_utils.py`（新）、`core/runner.py`、`core/flow/callbacks.py` |
| ✅ P3 | 移除 `insurance/tools/flow_evaluator.py` 的 side-effect 注册（`FlowEvaluatorRegistry.register(withdrawal_flow_evaluator)` 原本位于模块顶层），改由 `insurance/agent.py` 在 `create_insurance_agent` 里显式注册 | `agents/insurance/tools/flow_evaluator.py`、`agents/insurance/agent.py` |

> **复盘提醒**：上一轮出现"session 不落盘 / `active_tasks.json` 为空"的 bug，根因就是 `_turn_matched_skills` 存的是全名（`insurance.withdraw_money_flow`），而 Registry 的 key 是短名（`withdraw_money_flow`），evaluator 查找失败导致 `_flow_context` 未初始化。P0-a 的命名空间别名是根治方案。

---

## 二、剩余待 refactor 项

### 🟥 P1-1：`TaskRegistry` 重复实例化

**现状**
`TaskRegistry(sessions_dir)` 在三处被独立实例化：

```79:80:src/ark_agentic/core/tools/resume_task.py
registry = TaskRegistry(base_dir=self._sessions_dir)
```

```127:127:src/ark_agentic/core/flow/callbacks.py
self._task_registry = TaskRegistry(sessions_dir)
```

```308:308:src/ark_agentic/core/flow/callbacks.py
registry = TaskRegistry(base_dir=self._sessions_dir)
```

**问题**
- `TaskRegistry` 内部持有文件锁 / 缓存（未来若引入），多实例会出现数据竞争。
- `callbacks.py` 里 `self._task_registry` 和第 308 行的局部 `registry` 指向不同实例，逻辑不一致。
- 调用方需反复传 `sessions_dir`，容易传错。

**建议**
1. `TaskRegistry` 改为 **DI 单例**：在 `create_agent` 里构造一次，通过 agent context / session state 共享。
2. `FlowCallbacks` 和 `ResumeTaskTool` 都从同一来源拿实例，而非自建。
3. 现有 `_inject_evaluator_task_registry` 机制可复用（evaluator 已经拿到 shared registry），只需把 tool 侧也接入。

**改动面**：`core/flow/callbacks.py`、`core/flow/base_evaluator.py`、`core/tools/resume_task.py`、`agents/*/agent.py`（DI 接入点）。
**风险**：低；改造点都有类型边界。

---

### 🟥 P1-2：`auto_commit_tool_stages` 对混合字段阶段无能为力

**现状**
```286:304:src/ark_agentic/core/flow/base_evaluator.py
# 仅当所有 field_sources 都是 source="tool" 才自动 commit
all_tool = all(fs.source == "tool" for fs in stage.field_sources.values())
if not all_tool:
    continue
```

**问题**
- 一个阶段若同时含 `source="user"` 和 `source="tool"` 字段（合理的业务场景，比如用户确认 + 后端返回参考号），自动提交就整体失效，必须等 LLM 显式调 `CollectUserFieldsTool` 才推进。
- 目前业务层通过"拆分阶段"绕开（`plan_confirm` 纯 user → `execute` 纯 tool），但本质是框架能力不足带来的业务侧 workaround。

**建议**
把提交条件从"阶段级"降到"字段级"：
- 阶段每个 tool 字段就绪就合并进 `_flow_context.stages[stage_id]`（部分提交）。
- 所有字段（含 user）齐备后再触发阶段完成事件。
- `CollectUserFieldsTool` 与 auto-commit 写同一份阶段数据 dict，而不是各走各的。

**改动面**：`core/flow/base_evaluator.py::auto_commit_tool_stages`、`core/flow/collect_user_fields.py`、`core/flow/callbacks.py::after_tool_auto_commit`。
**风险**：中；涉及状态合并语义，需要补单测覆盖"部分提交后再补 user 字段"的路径。

---

### 🟨 P2-1：Checkpoint 持久化与 `__completed__` 哨兵耦合

**现状**
```214:214:src/ark_agentic/core/flow/callbacks.py
result.current_stage.id if result.current_stage else "__completed__",
```
```291:294:src/ark_agentic/core/flow/callbacks.py
# 流程已全部完成（__completed__）时始终写盘以触发 TaskRegistry 清理。
# _flow_context._needs_persist=True（由 rollback 设置）时强制写盘。
needs_persist = bool(flow_ctx.get("_needs_persist"))
if current_stage_id != "__completed__" and not needs_persist:
```

**问题**
`persist_flow_context` 的写盘判断包含三条并行规则：
1. `checkpoint=True` 的阶段完成后写盘；
2. 流程整体完成（`__completed__` 魔法字符串）始终写盘以便清理；
3. rollback 设置 `_needs_persist=True` 强制写盘。

这些规则散落在 callback、evaluator 和 rollback tool 中，后续新增特殊场景（如 pause/resume、并行流程）极易遗漏某一条。`__completed__` 用字符串做哨兵也不够健壮。

**建议**
1. 把写盘触发因子抽成枚举/事件（`PersistReason.CHECKPOINT | COMPLETED | ROLLBACK | FORCED`），`FlowEvalResult` 携带该字段，`persist_flow_context` 只看它。
2. `__completed__` 改为 `FlowEvalResult.is_done=True` 语义判断，不再在字段里拼魔法串。
3. `_needs_persist` 字段从 `flow_ctx` 提到 `FlowEvalResult` 里，避免跨层污染状态。

**改动面**：`core/flow/base_evaluator.py`（`FlowEvalResult` 扩展）、`core/flow/callbacks.py`、`core/flow/rollback_flow_stage.py`、`core/flow/task_registry.py`（去掉字符串匹配）。
**风险**：中；需要配套迁移已落盘的 `active_tasks.json`（或加兼容读）。

---

### 🟨 P2-2：Hook 顺序依赖脆弱

**现状**
Flow 机制依赖 hook 执行顺序：
- `before_model_flow_eval` 必须在 `_enrich_skills_with_stage_reference` 前运行（确保 `_flow_context` 已就绪）。
- `after_tool_auto_commit` 必须在 guardrails 后、`persist_flow_context` 前（确保 state_delta 应用完）。
- `strip_temp_state` 必须在 `after_agent` 末尾（否则 `_turn_matched_skills` 会污染下一轮）。

但这些顺序依赖全靠 `create_*_agent` 里手写 `RunnerCallbacks(before_model=[...], ...)` 的列表顺序维护，没有检查机制。

**建议**
1. 给 callback 函数加 `@requires(..., provides=...)` 声明式元数据，`RunnerCallbacks` 构造时做拓扑排序 + 循环依赖检测。
2. 或者至少在 `RunnerCallbacks` 文档里用表格固化顺序约定 + runtime assert。

**改动面**：`core/callbacks.py`、各 `create_*_agent`。
**风险**：低；纯加约束不改逻辑。

---

### 🟨 P2-3：Reference 文件注入分散在两处

**现状**
- `_enrich_skills_with_stage_reference`（runner 里）负责把当前阶段的 reference .md 塞进 `SkillEntry.content`。
- `before_model_flow_eval`（callbacks 里）负责把 pending task 提示、未收集字段提示、可用 checkpoint 塞进 system prompt。

两者都是"往 LLM 上下文里注入 flow 相关的文字"，却在不同模块、用不同方式（一个改 skill、一个改 messages）。

**建议**
统一到 `before_model_flow_eval`：一次性把 reference + 状态 + 字段 hint 拼好，要么全部走 skill content，要么全部走 system message。选一种一致策略。

**改动面**：`core/runner.py::_enrich_skills_with_stage_reference`、`core/flow/callbacks.py::before_model_flow_eval`。
**风险**：低；纯重构，token 预算可能需要重新 review。

---

### 🟩 P3-1：Evaluator 对 skill/reference 目录布局的隐式假设

**现状**
`StageDefinition.reference_file="plan_confirm.md"` 会被拼成 `{skill_dir}/references/{reference_file}`，这个路径约定只在 runner 的文件读取代码里隐式体现，evaluator 自身无感知。

**问题**
- 若业务想把 reference 放到别处（共享库、CDN 远程拉取），必须改 runner 而不是 evaluator。
- 目录缺失时是静默 fallback，不易发现配置错误。

**建议**
1. Reference 解析委托给一个 `ReferenceResolver` 接口，默认实现走 skill 目录约定。
2. evaluator 通过构造参数注入 resolver；runner 不再直接读文件。

**改动面**：`core/runner.py`、`core/flow/base_evaluator.py`、各 agent 工厂。
**风险**：低；但工作量中等，涉及缓存策略迁移。

---

### 🟩 P3-2：文档与代码一致性机制缺失

**现状**
`SKILL.md`、`references/*.md`、`StageDefinition.stages`、`FlowEvaluator` 这四处信息需要手动保持同步。例如上一轮加 `double_confirm` 阶段就改了 4 个文件，任何遗漏都是潜在 bug。

**建议**
1. 写个 CI check：`StageDefinition.reference_file` 指向的文件必须存在，`field_sources` 键必须在 `output_schema` 里。
2. `SKILL.md` 的"用户字段阶段"表格考虑从 stages 自动生成（build 时渲染 md）。

**改动面**：新增 `scripts/validate_flows.py` + CI。
**风险**：无；纯加检查。

---

### 🟩 P3-3：Evaluator 全局单实例 vs 多 Agent 隔离

**现状**
`FlowEvaluatorRegistry._registry` 是类变量，全进程共享。
```5:5:src/ark_agentic/core/flow/base_evaluator.py
  - before_model hook: 调用 evaluate() 注入当前阶段状态到系统提示
```
（Registry 具体实现见 `base_evaluator.py` 底部）

**问题**
- 若未来 `insurance` 和 `securities` 两个 agent 同名 skill（都叫 `withdraw_flow`），短名注册会互相覆盖；命名空间别名能解决查询路径，但短名入口仍冲突。
- 单测场景下测试间会相互污染（已经有隐性表现）。

**建议**
1. `FlowEvaluatorRegistry` 改为实例化（per agent），`create_*_agent` 构造自己的 registry。
2. 或保留全局但强制要求 `register` 必须带 `namespace`，拒绝短名直写。

**改动面**：`core/flow/base_evaluator.py`、`core/flow/callbacks.py`、各 agent 工厂。
**风险**：中；是否多实例化与 P1-1（TaskRegistry DI）一并设计更划算。

---

## 三、长期架构方向

> 以下不是具体 refactor 项，而是做上面项时需要对齐的目标架构，避免多轮局部改造互相打架。

### 分层目标

```
┌─ Agent Layer ─────────────────────────┐
│  business skills / domain logic       │
│  StageDefinition / output_schema      │
└──────────────┬────────────────────────┘
               │  uses
┌──────────────▼────────────────────────┐
│ Flow Framework Layer                   │
│  ├─ Orchestrator (hooks 编排 & 顺序)   │
│  ├─ Evaluator Registry (per agent)     │
│  ├─ TaskRegistry (DI 单例)             │
│  └─ ReferenceResolver                  │
└──────────────┬────────────────────────┘
               │  uses
┌──────────────▼────────────────────────┐
│ Core Runtime                          │
│  RunnerCallbacks / state_utils / LLM  │
└───────────────────────────────────────┘
```

### 关键约定

1. **Framework 层不 import 具体业务 evaluator**（已实现）；业务层显式注册（已实现）。
2. **所有可变状态通过 `state_delta` 流动**（已实现，但 `_needs_persist` 破例，见 P2-1）。
3. **Hook 之间通过声明式依赖编排**（见 P2-2），而不是列表顺序。
4. **Agent 工厂是唯一的 DI 装配点**（见 P1-1 / P3-3），不允许模块顶层 side effect。

---

## 四、建议推进顺序

1. **第一阶段（1~2 天）**：P1-1（TaskRegistry DI）+ P3-3（Registry per agent）一起做，它们都是 DI 改造，放一起 mental model 一致。
2. **第二阶段（2~3 天）**：P1-2（auto-commit 字段级）+ P2-1（写盘触发因子枚举），这两项都修改 `FlowEvalResult`，捆绑改能复用改造成本。
3. **第三阶段（1 天）**：P2-2（Hook 依赖声明）+ P2-3（Reference 注入统一），纯整理。
4. **第四阶段（按需）**：P3-1（ReferenceResolver）、P3-2（CI 一致性检查）。

每个阶段结束必须跑一次 `insurance.withdraw_money_flow` 完整 5 阶段 smoke test（含 rollback 和 discard 路径）。

---

## 附：关联文档

- `plans/taskflow_design.md` — Flow 机制详细设计
- `plans/flow_dsl_refactor.md` — 早期 DSL 重构讨论
- `src/ark_agentic/core/flow/base_evaluator.py` 模块 docstring — 当前运行时约定
