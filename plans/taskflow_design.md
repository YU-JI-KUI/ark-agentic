**"非侵入式 Agentic Native TaskFlow"** 设计文档。

这份方案的核心思想是：**不修改框架底层，通过"资源引用（Reference）+ 状态工具（Evaluator）+ 增量状态（State Delta）"实现复杂 SOP 编排。**

---

# 设计文档：基于资源引用与状态工具的 Agentic Native TaskFlow 方案

## 1. 设计哲学

* **最小侵入性 (Minimal-Intrusive)**：不改动 `AgentRunner` 的核心 ReAct 循环逻辑；
  需要在框架层新增 `SkillLoader` reference 扫描、`_build_system_prompt()` Dynamic 注入、
  以及 `state_delta` 点路径合并三处改动，改动均为增量扩展，不破坏现有行为。
* **智能体原生 (Agentic Native)**：将流程编排从"框架硬编码"下沉为"Agent 的工具决策与知识检索"。
* **按需内化 (Lazy Loading)**：通过 `reference` 解决 SKILL 臃肿问题，仅在需要时加载指令。
* **状态驱动 (State-Driven)**：利用现有 `session.state` 实现跨会话的任务持久化与恢复。

**与传统 DAG 编排引擎的区别**：
- 传统方案在 ReAct 之上叠加编排层（FlowEngine），需要新增 FlowEngine / Store / Router 三个框架模块，框架代码维护成本高。
- 本方案将编排能力"溶解"到工具和状态中，零改动 AgentRunner，每个业务独立实现 Evaluator，互不影响。

**核心信任链**：

```
flow_evaluator（确定性状态机）
  → 首次调用时检测是否有待恢复任务（InEvaluator Pending Detection）
  → state_delta 写入 _flow_stage
    → 框架自动注入当前阶段 reference
      → Agent 按 SOP 执行业务工具（结果写入 session.state）
        → Agent 调用 commit_flow_stage(stage_id, user_data)
            → 框架按 field_sources 自动提取 tool 来源字段
            → LLM 提供 user 来源字段（via user_data）
            → Pydantic 校验通过 → 写入 _flow_context.stage_<id>
            → checkpoint 阶段 → 追加到 _flow_context.checkpoints
          → flow_evaluator 再评估（Pydantic 校验通过 → 进入下一阶段）
  → after_agent: persist_flow_context（仅 checkpoint 阶段触发写盘）
```

---

## 2. 核心组件设计

### 2.1 SKILL 结构与 Reference 定义

`references/` 是 SKILL 目录下的**可选子目录**，与 `SKILL.md` 同级。`SKILL.md` 的 frontmatter 中不再声明 `references:` 索引，reference 文档通过正文中的相对路径直接引用。

**目录结构**：

```
skills/withdraw_money_flow/
├── SKILL.md                  # 主 SKILL 文件
└── references/               # 可选：阶段 SOP 文档
    ├── identity_verify.md
    ├── options_query.md
    ├── plan_confirm.md
    └── execute.md
```

**SKILL.md frontmatter 示例**：

```yaml
required_tools:
  - withdraw_money_flow_evaluator
  - commit_flow_stage
  - rollback_flow_stage
  - customer_info
  - policy_query
  - rule_engine
  - render_a2ui
  - submit_withdrawal
  - resume_task
```

**SKILL.md 流程回退规则**（通用，不依赖具体阶段名称）：

```markdown
## 流程回退

当用户希望修改已完成阶段的内容（如更换方案、重新查询等）：

1. 查看 evaluator 响应中的 `available_checkpoints` 列表
2. 根据用户意图找到最合适的回退点：
   - **明确匹配**：告知用户将回退到「XX阶段」重新执行，等待用户确认
   - **无法判断**：将 `available_checkpoints` 列表全部展示，请用户指定
3. 用户确认后调用 `rollback_flow_stage(stage_id=<确认的 stage_id>)`
4. 工具自动清除目标阶段及其后续所有阶段的数据
5. 再次调用 flow_evaluator，从目标阶段重新开始执行
```

---

### 2.2 流程评估工具 (FlowEvaluator) — 基类 + 业务继承模式

**这是最核心的变更**。框架层提供 `BaseFlowEvaluator` 抽象基类，每个业务流程继承它并仅需定义阶段列表，本质是一个**确定性状态机**包装为 AgentTool：

```python
@dataclass
class FieldSource:
    """阶段 schema 字段的数据来源声明。

    source="tool": 框架从 session.state[state_key] 自动提取，LLM 无需传值。
    source="user": LLM 必须通过 commit_flow_stage(user_data=...) 明确提供。

    提取逻辑（source="tool" 时，优先级：transform > path > 直接取值）：
      transform: 调用 transform(state_value) 得到字段值
      path:      按点路径遍历 state_value（如 "identity.verified"）
      否则：     直接使用 state_value 本身
    """
    source: Literal["tool", "user"] = "user"
    state_key: str | None = None
    path: str | None = None
    transform: Callable | None = None
    description: str | None = None  # 仅 source="user" 时有意义，供 evaluator 向模型说明


@dataclass
class StageDefinition:
    """阶段定义。

    checkpoint=True: 该阶段完成后触发 persist_flow_context 写盘，建立跨会话恢复点。
                     同时记录到 _flow_context.checkpoints，作为 rollback_flow_stage 的合法目标。

    delta_state_keys: 额外快照的 session.state 键（不参与 field_sources 校验）。
                      用于 resume 时将工具原始输出还原到 session.state，
                      使下游工具（如 submit_withdrawal 读取 _plan_allocations）在恢复后可用。
    """
    id: str
    name: str
    description: str
    required: bool = True
    output_schema: type[BaseModel] | None = None
    reference_file: str | None = None
    tools: list[str] = field(default_factory=list)
    field_sources: dict[str, FieldSource] = field(default_factory=dict)
    checkpoint: bool = False
    delta_state_keys: list[str] = field(default_factory=list)
```

#### Evaluator 内置待恢复任务检测

`BaseFlowEvaluator.execute()` 在首次调用时（无 `_flow_context.flow_id`）自动检测是否存在待恢复任务，**不依赖 `before_agent` hook**：

```
优势：
  - 只有在 SKILL 被实际调用时才触发检测（用户问无关问题不受影响）
  - 检测结果以工具结果形式返回，LLM 在同一轮决策中处理
  - session 内只检测一次（_pending_checked_{skill_name} 标记防止重复）
```

```python
class BaseFlowEvaluator(AgentTool, ABC):
    def __init__(self) -> None:
        self.name = f"{self.skill_name}_evaluator"
        self._task_registry: TaskRegistry | None = None  # 由 create_agent_tools() 注入
        self._ttl_hours: int = 72

    async def execute(self, tool_call, context=None):
        ctx = context or {}
        flow_ctx = dict(ctx.get("_flow_context") or {})

        # ── 待恢复任务检测（session 内只执行一次）──
        _pending_flag = f"_pending_checked_{self.skill_name}"
        if (
            not flow_ctx.get("flow_id")
            and self._task_registry is not None
            and not ctx.get(_pending_flag)
        ):
            user_id = str(ctx.get("user:id", ""))
            if user_id:
                active = self._task_registry.list_active(user_id, ttl_hours=self._ttl_hours)
                pending = [t for t in active if t.get("skill_name") == self.skill_name]
                if pending:
                    task = pending[0]
                    return AgentToolResult(
                        content={
                            "status": "pending_task_detected",
                            "pending_task": {
                                "flow_id": task["flow_id"],
                                "skill_name": task["skill_name"],
                                "current_stage": task["current_stage"],
                            },
                            "instruction": "...",  # 继续/废弃/重新开始操作指引
                        },
                        metadata={"state_delta": {_pending_flag: True}},
                    )

        # ── 正常流程评估 ──
        if not flow_ctx.get("flow_id"):
            flow_ctx = {"flow_id": str(uuid.uuid4()), "skill_name": self.skill_name}

        completed, is_done = self._evaluate_stages(flow_ctx)

        if is_done:
            return AgentToolResult(content={"flow_status": "completed", ...})

        current_stage = ...
        available_checkpoints = list(flow_ctx.get("checkpoints") or [])  # 供 rollback 决策使用

        return AgentToolResult(
            content={
                "flow_status": "in_progress",
                "current_stage": current_stage_info,
                "completed_stages": completed,
                "available_checkpoints": available_checkpoints,  # ★ LLM 据此决定回退目标
                "instruction": self._build_instruction(current_stage),
            },
            metadata={"state_delta": state_delta},
        )
```

**业务层继承示例**（取款流）：

```python
class WithdrawalFlowEvaluator(BaseFlowEvaluator):
    @property
    def skill_name(self) -> str:
        return "withdraw_money_flow"

    @property
    def stages(self) -> list[StageDefinition]:
        return [
            StageDefinition(
                id="identity_verify",
                name="身份核验",
                checkpoint=True,   # 完成后持久化，断线可从方案查询阶段恢复
                output_schema=IdentityVerifyOutput,
                reference_file="identity_verify.md",
                tools=["customer_info", "policy_query"],
                field_sources={
                    "user_id":         FieldSource("tool", "_customer_info_result", "user_id"),
                    "id_card_verified": FieldSource("tool", "_customer_info_result", "identity.verified"),
                    "policy_ids":      FieldSource("tool", "_policy_query_result",
                        transform=lambda r: [p["policy_id"] for p in r.get("policyAssertList", [])]),
                },
            ),
            StageDefinition(
                id="options_query",
                name="方案查询",
                checkpoint=False,  # 纯查询，可重新执行，不建立恢复点
                output_schema=OptionsQueryOutput,
                reference_file="options_query.md",
                tools=["rule_engine"],
                field_sources={
                    "available_options": FieldSource("tool", "_rule_engine_result", "options"),
                    "total_cash_value":  FieldSource("tool", "_rule_engine_result", "total_available_excl_loan"),
                    "max_withdrawal":    FieldSource("tool", "_rule_engine_result", "total_available_incl_loan"),
                },
            ),
            StageDefinition(
                id="plan_confirm",
                name="方案确认",
                checkpoint=True,   # 用户明确确认方案后持久化，断线可从执行阶段恢复
                output_schema=PlanConfirmOutput,
                reference_file="plan_confirm.md",
                tools=["render_a2ui"],
                field_sources={
                    "confirmed":       FieldSource("user", description="用户是否确认方案"),
                    "selected_option": FieldSource("user", description="选中方案（channels + target）"),
                    "amount":          FieldSource("user", description="最终取款金额（元）"),
                },
                delta_state_keys=["_plan_allocations"],  # render_a2ui 写入，resume 时还原供 submit_withdrawal 使用
            ),
            StageDefinition(
                id="execute",
                name="执行取款",
                checkpoint=False,  # 最终态，__completed__ 路径自动清理记录
                output_schema=ExecuteOutput,
                reference_file="execute.md",
                tools=["submit_withdrawal"],
                field_sources={
                    "submitted": FieldSource("tool", "_submitted_channels",
                        transform=lambda channels: bool(channels)),
                    "channels":  FieldSource("tool", "_submitted_channels"),
                },
            ),
        ]

# 业务层初始化（create_insurance_tools() 中）
withdrawal_flow_evaluator._task_registry = TaskRegistry(sessions_dir)
FlowEvaluatorRegistry.register(withdrawal_flow_evaluator)
```

---

### 2.2.1 CommitFlowStageTool — 阶段数据提交工具

**问题背景**：业务工具（`customer_info`、`rule_engine` 等）将结果写入各自的 state key（如 `_customer_info_result`），字段名和路径与阶段 schema 不一定一致，且部分字段来自用户对话而非工具调用。

**解决方案**：`CommitFlowStageTool` 按 `StageDefinition.field_sources` 声明完成以下工作：

1. `source="tool"` 字段：从 `session.state[state_key]` 自动提取（支持点路径和 transform）
2. `source="user"` 字段：从 `user_data` 参数取值（要求 LLM 从对话上下文提供）
3. Pydantic 校验合并后的数据
4. 写入 `_flow_context.stage_<id>`（点路径，不覆盖同级 key）
5. **捕获 stage delta**：将 `source="tool"` 字段对应的 `state_key` 原始值写入 `stage_<id>_delta`，供跨会话恢复时还原工具上下文
6. **额外 delta 捕获**：将 `delta_state_keys` 中的 state key 一并写入 `stage_<id>_delta`（不参与 schema 校验，用于 resume 还原下游工具依赖）
7. **checkpoint 记录**：若 `stage.checkpoint=True`，将 `{stage_id, name, description}` 追加到 `_flow_context.checkpoints`，供 `rollback_flow_stage` 使用

```python
# 写入 _flow_context.stage_<id>
state_delta = {f"_flow_context.stage_{stage_id}": collected}

# checkpoint 阶段：记录到 checkpoints 历史（幂等，重复提交时替换）
if stage.checkpoint:
    existing = [c for c in flow_ctx.get("checkpoints", []) if c["stage_id"] != stage_id]
    existing.append({"stage_id": stage_id, "name": stage.name, "description": stage.description})
    state_delta["_flow_context.checkpoints"] = existing

# 捕获 delta（source="tool" 字段 + delta_state_keys）
stage_delta = {}
for fs in stage.field_sources.values():
    if fs.source == "tool" and fs.state_key not in stage_delta:
        raw = ctx.get(fs.state_key)
        if raw is not None:
            stage_delta[fs.state_key] = raw
for key in stage.delta_state_keys:      # ★ 额外快照（如 _plan_allocations）
    if key not in stage_delta:
        raw = ctx.get(key)
        if raw is not None:
            stage_delta[key] = raw
if stage_delta:
    state_delta[f"_flow_context.stage_{stage_id}_delta"] = stage_delta
```

**字段来源决策树**：

```
对于阶段的每个 schema 字段：
  ├── source="tool"
  │     ├── transform 有值 → transform(session.state[state_key])
  │     ├── path 有值     → 点路径遍历 session.state[state_key]
  │     └── 否则          → session.state[state_key] 直接赋值
  └── source="user"       → user_data[field_name]（LLM 必须提供）

额外写入 delta（不校验）：
  delta_state_keys 中的每个 key → session.state[key] 原始值
```

---

### 2.2.2 RollbackFlowStageTool — 阶段回退工具

允许在流程中途回退到任意已完成的 checkpoint 阶段，清除目标阶段及其后续所有阶段的数据。

**设计原则**：
- 只能回退到 `checkpoint=True` 且已完成的阶段（`_flow_context.checkpoints` 中有记录）
- 清除目标阶段及后续所有阶段的 `stage_<id>` 和 `stage_<id>_delta`
- 同步从 `_flow_context.checkpoints` 移除已清除阶段的记录
- LLM 负责意图判断和用户确认，工具只执行清除操作

**交互流程**：

```
用户："我想换一个方案"（处于 execute 阶段）
  │
  ▼
LLM 读取 available_checkpoints: [
    {"stage_id": "identity_verify", "name": "身份核验", ...},
    {"stage_id": "plan_confirm",    "name": "方案确认", ...}
]
  │
  ▼
LLM 判断意图匹配 plan_confirm → 告知用户：
"我将为您回退到「方案确认」阶段，重新选择方案，是否确认？"
  │
用户确认
  │
  ▼
LLM 调用 rollback_flow_stage(stage_id="plan_confirm")
  → 清除 stage_plan_confirm、stage_plan_confirm_delta
  → 清除 stage_execute、stage_execute_delta
  → 更新 _flow_context.checkpoints（移除 plan_confirm 记录）
  │
  ▼
LLM 调用 flow_evaluator
  → 检测 plan_confirm 无数据 → current_stage = plan_confirm
  → 重新展示方案，收集用户确认
```

```python
class RollbackFlowStageTool(AgentTool):
    """将流程回退到指定 checkpoint 阶段，清除目标及后续所有阶段的已完成数据。"""
    name = "rollback_flow_stage"

    async def execute(self, tool_call, context=None):
        target_stage_id = tool_call.arguments["stage_id"]
        flow_ctx = (context or {}).get("_flow_context") or {}
        evaluator = FlowEvaluatorRegistry.get(flow_ctx.get("skill_name", ""))

        # 校验：必须是 checkpoint 且已在 checkpoints 历史中
        target_stage = next(s for s in evaluator.stages if s.id == target_stage_id)
        if not target_stage.checkpoint:
            return error("只能回退到 checkpoint 阶段")
        recorded = flow_ctx.get("checkpoints") or []
        if not any(c["stage_id"] == target_stage_id for c in recorded):
            return error("目标阶段尚未完成，无需回退")

        # 清除目标及后续阶段
        target_idx = [s.id for s in evaluator.stages].index(target_stage_id)
        stages_to_clear = evaluator.stages[target_idx:]
        state_delta = {}
        for stage in stages_to_clear:
            state_delta[f"_flow_context.stage_{stage.id}"] = {}
            state_delta[f"_flow_context.stage_{stage.id}_delta"] = {}

        # 更新 checkpoints 历史
        cleared_ids = {s.id for s in stages_to_clear}
        state_delta["_flow_context.checkpoints"] = [
            c for c in recorded if c["stage_id"] not in cleared_ids
        ]

        return AgentToolResult(
            content={
                "status": "rolled_back",
                "target_stage": {"id": target_stage_id, "name": target_stage.name},
                "cleared_stages": [s.id for s in stages_to_clear],
                "message": f"已回退到【{target_stage.name}】阶段，请再次调用 {evaluator.name} 重新执行。",
            },
            metadata={"state_delta": state_delta},
        )
```

---

### 2.3 Reference 框架级透明注入

Reference 的加载对 SKILL 完全透明——SKILL.md 不需要显式提及 reference 文件，框架根据加载模式自动处理。

#### FULL 模式（全量注入）

**注入点**：`SkillLoader._load_skill_file()` 加载 SKILL.md 时，自动扫描 `references/` 子目录，将所有 `.md` 文件内容追加到 `SkillEntry.content`。

**适用场景**：reference 文件较少或内容较短的 SKILL。

#### Dynamic 模式（状态驱动按需注入）

**注入点**：`AgentRunner._build_system_prompt()` 读取 `session.state["_flow_stage"]`，仅注入当前阶段对应的 reference。

```python
# AgentRunner._build_system_prompt() 中
current_stage_id = state.get("_flow_stage")
if current_stage_id and current_stage_id != "__completed__" and skills:
    skills = self._enrich_skills_with_stage_reference(skills, current_stage_id)
```

`_enrich_skills_with_stage_reference()` 通过 `FlowEvaluatorRegistry.get(skill.id)` 反查 evaluator，使用 `StageDefinition.reference_file` 字段定位文件（与 `stage.id` 解耦），避免文件名不一致导致静默失败。

**适用场景**：多阶段流程，每个阶段的 reference 内容较大。

#### 模式选择（自动判断，无需配置）

| 条件 | 使用模式 |
|------|---------|
| SKILL 无 `references/` 目录 | 无注入 |
| SKILL 有 `references/`，无 `_flow_stage` | FULL |
| SKILL 有 `references/` + `_flow_stage` 已设置 | Dynamic |

---

### 2.4 上下文管理与 `state_delta`

**`_flow_context` 内部结构**：

```python
session.state["_flow_context"] = {
    "flow_id": "uuid-xxx",
    "skill_name": "withdraw_money_flow",

    # 各阶段数据（commit_flow_stage 写入）
    "stage_identity_verify": {"user_id": "U001", "id_card_verified": True, "policy_ids": [...]},
    "stage_identity_verify_delta": {"_customer_info_result": {...}, "_policy_query_result": {...}},

    "stage_options_query": {"available_options": [...], ...},
    "stage_options_query_delta": {"_rule_engine_result": {...}},

    "stage_plan_confirm": {"confirmed": True, "selected_option": {...}, "amount": 2000.0},
    "stage_plan_confirm_delta": {"_plan_allocations": [...]},  # delta_state_keys 捕获

    # checkpoint 历史（commit_flow_stage 在 checkpoint 阶段时维护）
    "checkpoints": [
        {"stage_id": "identity_verify", "name": "身份核验", "description": "验证客户身份和保单信息"},
        {"stage_id": "plan_confirm",    "name": "方案确认", "description": "向用户展示方案并等待确认"},
    ],
}
```

**点路径 state_delta 合并**（`AgentRunner._apply_state_delta()`）：

```python
# ✅ 正确：点路径格式，不整体替换父对象
metadata={"state_delta": {"_flow_context.stage_identity_verify": {...}}}

# ❌ 错误：整体替换 _flow_context，会清空其他阶段数据
metadata={"state_delta": {"_flow_context": {"stage_identity_verify": {...}}}}
```

---

## 3. 持久化与跨会话恢复机制

### 3.1 任务注册表 (Task Registry)

* **文件路径**：`{sessions_dir}/{user_id}/active_tasks.json`
* `TaskRegistry.upsert()` 在 `current_stage="__completed__"` 时自动删除该记录

每个 stage 快照包含三个子字段：

| 字段 | 说明 |
|------|------|
| `status` | `"completed"` \| `"pending"` |
| `data` | 经 Pydantic 校验的 schema 数据 |
| `delta` | `source="tool"` 字段 + `delta_state_keys` 的 state_key 原始值，恢复后还原到 `session.state` 顶层 |

```json
{
  "active_tasks": [
    {
      "flow_id": "uuid-xxx",
      "skill_name": "withdraw_money_flow",
      "current_stage": "execute",
      "last_session_id": "session_xxx",
      "updated_at": 1744444900000,
      "resume_ttl_hours": 72,
      "flow_context_snapshot": {
        "stages": {
          "identity_verify": {
            "status": "completed",
            "data": {"user_id": "U001", "id_card_verified": true, "policy_ids": ["POL001"]},
            "delta": {
              "_customer_info_result": {...},
              "_policy_query_result": {...}
            }
          },
          "options_query": {
            "status": "completed",
            "data": {"available_options": [...], ...},
            "delta": {"_rule_engine_result": {...}}
          },
          "plan_confirm": {
            "status": "completed",
            "data": {"confirmed": true, "selected_option": {...}, "amount": 2000.0},
            "delta": {"_plan_allocations": [...]}  // delta_state_keys 捕获
          },
          "execute": {"status": "pending", "data": {}, "delta": {}}
        }
      }
    }
  ]
}
```

---

### 3.2 持久化 Hook：`persist_flow_context` (after_agent)

**Checkpoint 检查机制**：仅在最后一个已完成阶段标记了 `checkpoint=True` 时写盘。流程全部完成时（`__completed__`）始终写盘，触发 TaskRegistry 自动删除记录。

```python
async def persist_flow_context(self, ctx: CallbackContext, *, response: AgentMessage):
    flow_ctx = session.state.get("_flow_context")
    restorable = evaluator.get_restorable_state(flow_ctx)
    current_stage_id = restorable["current_stage"]

    # 非 __completed__ 时检查 checkpoint
    if current_stage_id != "__completed__":
        completed_ids = [
            s.id for s in evaluator.stages
            if restorable["stages"].get(s.id, {}).get("status") == "completed"
        ]
        if not completed_ids:
            return None
        last_completed = next(s for s in evaluator.stages if s.id == completed_ids[-1])
        if not last_completed.checkpoint:
            return None  # 非 checkpoint 阶段，跳过写盘

    registry.upsert(user_id, flow_id, ..., current_stage=current_stage_id)
```

**取款流写盘时机**：

| 完成阶段 | checkpoint | 是否写盘 |
|---------|-----------|---------|
| identity_verify | ✓ | **写盘** |
| options_query | ✗ | 跳过（可重新查询）|
| plan_confirm | ✓ | **写盘** |
| execute → __completed__ | N/A | **写盘（清理记录）** |

---

### 3.3 恢复路径

#### Step 1: Evaluator 侧检测（InEvaluator Pending Detection）

替代原先的 `before_agent` hook。当用户问题触发相关 SKILL、LLM 调用 `flow_evaluator` 时，evaluator 首次执行检查 `TaskRegistry`，返回待恢复任务信息。

```
优点：
  - 只在用户问题实际相关时触发（用户问天气 → LLM 不调用 flow_evaluator → 零拦截）
  - 同一 session 内只检测一次（_pending_checked_{skill} 标记）
  - 检测结果以工具结果形式融入 ReAct 循环，无需系统提示污染
```

#### Step 2: `resume_task` 工具

支持 `action="resume"` 和 `action="discard"` 两种操作。

```python
class ResumeTaskTool(AgentTool):
    def _handle_resume(self, tool_call, task):
        """还原 _flow_context + delta + checkpoints 到 session.state。"""
        flow_ctx = self._snapshot_to_flow_context(task)
        # _snapshot_to_flow_context 内部重建 checkpoints 列表（从 checkpoint 阶段逆推）
        tool_state = self._extract_delta_state(task)
        state_delta = {"_flow_context": flow_ctx}
        state_delta.update(tool_state)  # 还原 _rule_engine_result、_plan_allocations 等

    def _handle_discard(self, ...):
        registry.remove(user_id, flow_id)
        # ★ 清空 _flow_context，防止 persist_flow_context 重新写入已废弃任务
        return AgentToolResult(..., metadata={"state_delta": {"_flow_context": {}}})

    def _snapshot_to_flow_context(self, task) -> dict:
        """snapshot → _flow_context 运行时格式，同时重建 checkpoints 列表。"""
        flow_ctx = {"flow_id": ..., "skill_name": ...}
        for stage_id, stage_info in snapshot["stages"].items():
            if stage_info["status"] == "completed":
                flow_ctx[f"stage_{stage_id}"] = stage_info["data"]
            if stage_info.get("delta"):
                flow_ctx[f"stage_{stage_id}_delta"] = stage_info["delta"]
        # 重建 checkpoints（从 evaluator.stages 定义中过滤已完成的 checkpoint 阶段）
        evaluator = FlowEvaluatorRegistry.get(task["skill_name"])
        flow_ctx["checkpoints"] = [
            {"stage_id": s.id, "name": s.name, "description": s.description}
            for s in evaluator.stages
            if s.checkpoint and snapshot["stages"].get(s.id, {}).get("status") == "completed"
        ]
        return flow_ctx
```

#### Step 3: 继续执行

恢复后 Agent 调用 `flow_evaluator`，读取已恢复的 `_flow_context`，校验前序阶段数据完整后返回当前阶段并继续。`_plan_allocations` 等下游工具依赖的 state key 已通过 `delta` 还原，`submit_withdrawal` 等工具可正常运行。

---

## 4. 整体架构图

```
┌─────────────────────────────────────────────────────────────────┐
│ SKILL.md (withdraw_money_flow)                                  │
│  required_tools: [withdraw_money_flow_evaluator, commit_flow_  │
│                   stage, rollback_flow_stage, ..., resume_task] │
│  正文: 流程概述 + 流程回退规则（通用，不依赖阶段名）            │
└──────────────┬──────────────────────────────────────────────────┘
               │
┌──────────────▼──────────────────────────────────────────────────┐
│ AgentRunner（最小改动：+Dynamic注入 / +点路径合并）              │
│                                                                 │
│  ReAct Loop:                                                    │
│   ┌─────────────────────────────────────────────────────────┐  │
│   │ 1. LLM 调用 flow_evaluator                              │  │
│   │    → 首次调用：检测待恢复任务（InEvaluator Detection）  │  │
│   │    → 返回: current_stage + available_checkpoints        │  │
│   │    → state_delta 更新 _flow_stage                       │  │
│   │                                                         │  │
│   │ 2. 框架自动注入当前阶段的 reference 内容                │  │
│   │                                                         │  │
│   │ 3. LLM 按 SOP 调用业务工具                             │  │
│   │                                                         │  │
│   │ 4. LLM 调用 commit_flow_stage                          │  │
│   │    → 提取 tool 来源字段 + 校验 + 写入 stage data       │  │
│   │    → checkpoint 阶段 → 追加 checkpoints 记录           │  │
│   │    → delta_state_keys → 写入 stage delta               │  │
│   │                                                         │  │
│   │ 5a. LLM 调用 flow_evaluator 确认推进                   │  │
│   │    → 下一阶段重复 2-4                                   │  │
│   │                                                         │  │
│   │ 5b. 用户要求回退 → LLM 查 available_checkpoints        │  │
│   │    → 用户确认 → rollback_flow_stage(stage_id)          │  │
│   │    → 清除目标及后续阶段数据                            │  │
│   │    → 重新调用 flow_evaluator 从目标阶段执行             │  │
│   └─────────────────────────────────────────────────────────┘  │
│                                                                 │
│  Hooks（不改动接口）：                                           │
│   after_agent → persist_flow_context（仅 checkpoint 阶段写盘） │
└──────────────┬──────────────────────────────────────────────────┘
               │
┌──────────────▼──────────────────────────────────────────────────┐
│ 持久化层                                                        │
│  {sessions_dir}/{user_id}/active_tasks.json                     │
│   → stages[].data（schema 数据）                                │
│   → stages[].delta（工具原始输出快照）                          │
│   → current_stage, updated_at, resume_ttl_hours                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 5. 执行流程详解

### 5.1 新建流程

```
1. 用户说"我要取钱"
2. SkillMatcher 匹配到 withdraw_money_flow SKILL
3. LLM 调用 withdraw_money_flow_evaluator
   → _flow_context 为空，_task_registry 检测无待恢复任务
   → 初始化: {flow_id: uuid, skill_name: ...}
   → state_delta 设置 _flow_stage = "identity_verify"
4. 下一轮 system prompt 自动包含 references/identity_verify.md
5. LLM 按 SOP 调用 customer_info, policy_query
6. LLM 调用 commit_flow_stage(stage_id="identity_verify", user_data={})
   → 自动提取 tool 字段 → Pydantic 校验 → 写入 stage_identity_verify
   → identity_verify.checkpoint=True → 追加 checkpoints 记录
7. LLM 调用 flow_evaluator
   → Pydantic 校验 IdentityVerifyOutput ✓ → current_stage = options_query
8. after_agent: persist_flow_context
   → last_completed=identity_verify（checkpoint=True）→ 写盘
9. 重复直到 plan_confirm 阶段
10. commit_flow_stage(plan_confirm) → checkpoints 追加 plan_confirm 记录
11. after_agent: 写盘（plan_confirm checkpoint=True）
12. 进入 execute 阶段 → submit_withdrawal → commit_flow_stage(execute)
13. flow_evaluator 返回 flow_status="completed"
14. after_agent: persist（__completed__）→ TaskRegistry 自动删除记录
```

### 5.2 跨会话恢复

```
1. 用户新会话说"我要取钱"
2. LLM 调用 withdraw_money_flow_evaluator
   → _flow_context 为空，_task_registry 检测到未完成任务（execute 阶段）
   → 返回 pending_task_detected，写入 _pending_checked_ 标记
3. LLM 向用户展示未完成任务，等待确认
4. 用户选择继续 → LLM 调用 resume_task(flow_id=..., action="resume")
   → 还原 _flow_context（含 checkpoints 列表）
   → 还原 _plan_allocations 等 delta 到 session.state 顶层
5. LLM 调用 flow_evaluator
   → 读取恢复的 _flow_context，前序阶段 Pydantic 校验通过
   → current_stage = execute
   → available_checkpoints = [identity_verify, plan_confirm]
6. LLM 按 execute 阶段 SOP 调用 submit_withdrawal
   → _plan_allocations 已从 delta 还原，submit_withdrawal 正常读取
```

### 5.3 流程回退（用户改方案）

```
1. 用户在 execute 阶段说"我想换一个方案"
2. LLM 调用 flow_evaluator
   → 返回 available_checkpoints: [identity_verify, plan_confirm]
3. LLM 判断意图匹配 plan_confirm，告知用户将回退到「方案确认」阶段
4. 用户确认 → LLM 调用 rollback_flow_stage(stage_id="plan_confirm")
   → 清除 stage_plan_confirm、stage_plan_confirm_delta
   → 清除 stage_execute、stage_execute_delta
   → _flow_context.checkpoints 移除 plan_confirm 记录
5. LLM 调用 flow_evaluator
   → plan_confirm 无数据 → current_stage = plan_confirm
   → available_checkpoints = [identity_verify]
6. 重新展示方案（render_a2ui）→ 用户选新方案
7. commit_flow_stage(plan_confirm) → 写入新方案数据
   → 追加新的 checkpoints 记录
8. after_agent: persist（plan_confirm checkpoint=True）→ 新方案写盘
9. 进入 execute 阶段 → submit_withdrawal 使用新 _plan_allocations
```

---

## 6. 与传统 DAG 编排方案的对比

| 维度 | 传统 DAG 编排（FlowEngine） | Agentic Native（本方案） |
|------|---------------------------|-------------------------|
| 框架改动 | 新增 FlowEngine/Store/Router 三模块 | 零改动，仅增加工具和 Hook |
| 步骤执行 | 框架强制顺序执行 | FlowEvaluator 确定性评估 + Agent 遵循 |
| 工具隔离 | ephemeral session + tools 白名单 | reference SOP 中指定（知识引导） |
| 数据校验 | 无（condition 表达式仅做路由） | Pydantic schema 严格校验 |
| 回退支持 | 需修改 DAG 拓扑 | rollback_flow_stage 通用工具 |
| 持久化粒度 | 每步写盘 | checkpoint 阶段写盘（可配置） |
| 灵活性 | 固定 DAG，变更需修改 frontmatter | Agent 可灵活应对异常和用户意图变更 |
| 可维护性 | 框架代码维护成本高 | 每个业务独立 Evaluator，互不影响 |

---

## 7. 新增文件清单

```
src/ark_agentic/
├── core/
│   ├── flow/
│   │   ├── base_evaluator.py          # BaseFlowEvaluator + StageDefinition(checkpoint/delta_state_keys)
│   │   │                              # + FlowEvaluatorRegistry + InEvaluator Pending Detection
│   │   ├── task_registry.py           # TaskRegistry（active_tasks.json 管理）
│   │   ├── commit_flow_stage.py       # CommitFlowStageTool（含 checkpoint 记录 + delta_state_keys）
│   │   ├── rollback_flow_stage.py     # RollbackFlowStageTool（回退到 checkpoint 阶段）
│   │   └── callbacks.py               # FlowCallbacks: persist_flow_context（checkpoint 检查）
│   └── tools/
│       └── resume_task.py             # ResumeTaskTool（discard 清空 _flow_context / resume 重建 checkpoints）
│
└── agents/insurance/
    ├── tools/
    │   └── flow_evaluator.py          # WithdrawalFlowEvaluator（4 阶段 + checkpoint + delta_state_keys）
    └── skills/withdraw_money_flow/
        ├── SKILL.md                   # 含流程回退通用规则
        └── references/
            ├── identity_verify.md
            ├── options_query.md
            ├── plan_confirm.md
            └── execute.md
```

---

## 8. 关键设计决策记录

### D1: Pending Task Detection 移入 Evaluator

**原设计**：`inject_flow_hint` 作为 `before_agent` hook，每条用户消息都触发磁盘 I/O 并注入系统提示。

**现设计**：检测逻辑移入 `BaseFlowEvaluator.execute()`，仅在相关 SKILL 被实际调用时触发。

**理由**：前置拦截对所有用户输入生效，无关问题被系统提示污染，LLM 偏离用户意图。移入 Evaluator 后，无关问题零开销，检测结果以工具结果形式融入 ReAct 循环。

### D2: Checkpoint 写盘策略

**原设计**：每个 `after_agent` 均写盘。

**现设计**：只有最后完成的阶段标记了 `checkpoint=True` 时才写盘。

**理由**：减少不必要的磁盘 I/O；非 checkpoint 阶段（如 `options_query`）可重新执行，无需持久化。

### D3: delta_state_keys 捕获机制

**问题**：`plan_confirm` 阶段的 `field_sources` 全为 `source="user"`，`_plan_allocations`（由 `render_a2ui` 写入）未被捕获到 delta，resume 后 `submit_withdrawal` 报"可用渠道: 无"。

**解决**：`StageDefinition.delta_state_keys` 允许声明额外需要快照的 state key，不参与 schema 校验，仅用于 resume 还原。

### D4: RollbackFlowStageTool 通用设计

**原做法**：在 `execute.md` 中硬编码"改方案时需重新 commit_flow_stage"的操作序列。

**现设计**：通用 `rollback_flow_stage` 工具 + SKILL.md 级别的通用回退规则，不依赖任何具体阶段名称，适用于所有业务流程。

### D5: discard 时清空 _flow_context

**问题**：若用户在 session 中已 resume 过任务（`_flow_context` 已写入 state），再选择 discard，`persist_flow_context` after_agent hook 会把刚删除的任务重新写回 active_tasks.json。

**修复**：`_handle_discard` 返回 `state_delta: {"_flow_context": {}}`，清空 session state 中的 `_flow_context`。
