# 设计文档：Agentic Native TaskFlow

> **更新日期**: 2026-04-29

---

## 1. 设计哲学

* **最小侵入性 (Minimal-Intrusive)**：不改动 `AgentRunner` 的核心 ReAct 循环逻辑；框架层新增 `SkillLoader` reference 按需加载、`FlowCallbacks` 两个 Hook、`state_delta` 点路径合并，均为增量扩展。
* **智能体原生 (Agentic Native)**：流程编排不依赖 LLM 主动调用评估器，而是由框架 Hook 在每轮 ReAct 循环的关键节点自动驱动评估与提交。
* **按需内化 (Lazy Loading)**：通过 `reference` 解决 SKILL 臃肿问题，仅在进入对应阶段时加载该阶段的 reference 文档。
* **状态驱动 (State-Driven)**：利用 `session.state` 实现跨会话的任务持久化与恢复。

**与传统 DAG 编排引擎的区别**：

| 维度 | 传统 DAG 编排（FlowEngine） | Agentic Native（本方案） |
|------|---------------------------|-------------------------|
| 框架改动 | 新增 FlowEngine/Store/Router 三模块 | 零改动，仅增加 Hook 和工具 |
| 步骤执行 | 框架强制顺序执行 | Hook 自动评估 + Agent 遵循 SOP |
| 工具隔离 | ephemeral session + tools 白名单 | reference SOP 中指定（知识引导） |
| 数据校验 | 无（condition 表达式仅做路由） | Pydantic schema 严格校验 |
| 回退支持 | 需修改 DAG 拓扑 | rollback_flow_stage 通用工具 |
| 持久化粒度 | 每步写盘 | checkpoint 阶段写盘（可配置） |
| 灵活性 | 固定 DAG，变更需修改 frontmatter | Agent 可灵活应对异常和用户意图变更 |

---

## 2. 核心架构

### 2.1 Hook 驱动模式

Evaluator 不是 LLM 工具，而是由 `FlowCallbacks` 的两个 Hook 自动驱动的确定性状态机：

```
┌─────────────────────────────────────────────────────────────────┐
│ ReAct Loop（每轮）                                               │
│                                                                  │
│  ┌─ before_model_flow_eval ──────────────────────────────────┐  │
│  │ 1. 确定活跃 evaluator（_flow_context.skill_name /          │  │
│  │    _turn_matched_skills 反查 Registry）                     │  │
│  │ 2. 检测 pending task（每轮直检 TaskRegistry）               │  │
│  │ 3. 初始化 flow_id（首次调用，无活跃流程且无 pending）       │  │
│  │ 4. 调用 evaluator.evaluate() 统一评估（含自动提交）         │  │
│  │    → 抽取字段 → Pydantic 校验 → 自动提交                    │  │
│  │ 5. state_delta 写入 session.state（含                      │  │
│  │    _flow_context.current_stage）                           │  │
│  │ 6. 注入评估结果（role="system" 结构化 JSON）                │  │
│  │    + 当前阶段 reference 到 system message                   │  │
│  └────────────────────────────────────────────────────────────┘  │
│                          ↓                                       │
│                    LLM 调用                                      │
│                          ↓                                       │
│  ┌─ before_tool_stage_guard（before_tool）─────────────────┐  │
│  │ 当前 stage 未完成 + tool_call.name 命中下游 stage.tools →   │  │
│  │ 合成 ToolLoopAction.STOP 工具结果，复用 _tool_phase 的     │  │
│  │ STOP 收尾路径，向用户输出固定话术。                         │  │
│  └────────────────────────────────────────────────────────────┘  │
│                          ↓                                       │
│                     ... 下一轮 ...                                │
│                                                                  │
│  ┌─ persist_flow_context（after_agent，整个 run 结束后）──────┐  │
│  │ 1. evaluator.get_persistable_context() 输出扁平 snapshot  │  │
│  │ 2. checkpoint 检查：仅最后完成阶段标记了 checkpoint=True   │  │
│  │    时写盘；__completed__ 时始终写盘（触发清理）             │  │
│  │ 3. render_task_name() → TaskRegistry.upsert()             │  │
│  └────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 核心信任链

```
before_model_flow_eval（每轮自动运行）
  → 检测 pending task（直检 TaskRegistry）
  → evaluate() 统一评估：
    → 抽取所有字段（state 自动抽取 + _user_input_ 暂存区）
    → 全部就绪 → Pydantic 校验 → 自动提交 → 写入 _flow_context.stage_<id>
    → checkpoint 阶段 → 追加到 _flow_context.checkpoints
    → 有缺失字段 / 校验失败 → 当前阶段 in_progress（fields[*].status=missing|error），
                              flow_ctx.current_stage 同步指向该阶段
    → 全部完成 → is_done=True，flow_ctx.current_stage="__completed__"
    → 评估结果作为 role="system" 结构化 JSON message 注入
  → before_tool_stage_guard: 越级调用下游 stage 工具 → ToolLoopAction.STOP + 固定话术
  → Agent 按 SOP 执行业务工具 / 收集用户输入
    → collect_user_fields → 写入 _user_input_{stage_id} 暂存区
    → 下一轮 before_model_flow_eval 再评估
  → after_agent: persist_flow_context（仅 checkpoint 阶段写盘）
```

---

## 3. 核心组件

### 3.1 BaseFlowEvaluator（ABC）

```python
class BaseFlowEvaluator(ABC):
    """流程评估器基类（框架层）。

    由 FlowCallbacks 的 Hook 自动驱动，业务层仅需实现 skill_name 和 stages。
    """

    @property
    @abstractmethod
    def skill_name(self) -> str: ...

    @property
    @abstractmethod
    def stages(self) -> list[StageDefinition]: ...

    @property
    def task_name_template(self) -> str:
        """任务名模板，默认退化为 skill_name，业务层按需覆写。
        可用变量来自已完成阶段 data（展平）+ flow_ctx 顶层键。
        未就绪变量渲染为字面量 "{待定}"。
        """
        return self.skill_name

    def evaluate(self, flow_ctx, state) -> FlowEvalResult:
        """统一评估：抽取所有字段 → 自动推进 → 返回结构化结果（供 before_model hook 调用）。"""

    def render_task_name(self, flow_ctx) -> str:
        """按 task_name_template 渲染任务名。"""

    def get_persistable_context(self, flow_ctx) -> dict:
        """返回扁平 flow_ctx 浅拷贝（运行时 = 持久化同形状），剔除 _user_input_*。"""

    def iter_delta_state(self, flow_ctx) -> Iterator[tuple[str, Any]]:
        """遍历所有 stage_*_delta，产出 (state_key, raw_value)，供 resume 还原 session.state。"""
```

**关键方法说明**：

| 方法 | 调用方 | 说明 |
|------|--------|------|
| `evaluate()` | `before_model_flow_eval` | 遍历阶段，抽取字段，自动提交就绪阶段，输出 `FlowEvalResult` |
| `_extract_all_fields()` | `evaluate()` 内部 | 统一从 `session.state` + `_user_input_{stage_id}` 暂存区抽取所有字段 |
| `_commit_stage()` | `evaluate()` 内部 | 唯一提交路径：写入 stage 数据、清理暂存区、处理 checkpoint、快照 delta |
| `render_task_name()` | `persist_flow_context` | 模板渲染，缺失变量返回 "{待定}" |
| `get_persistable_context()` | `persist_flow_context` | 输出扁平 snapshot（与运行时 `_flow_context` 同形状） |
| `iter_delta_state()` | `ResumeTaskTool._extract_delta_state` | 遍历 `stage_*_delta`，重建 session.state 中工具输出 |

### 3.2 FieldDefinition — 字段定义（替代 FieldSource）

```python
@dataclass
class FieldDefinition:
    """阶段字段定义 — 统一声明抽取策略。

    有 state_key → evaluator 自动从 session.state 抽取
    无 state_key → 需用户通过 collect_user_fields 提供（写入暂存区 _user_input_{stage_id}）
    两者都可以，evaluator 统一评估

    提取逻辑（仅 state_key 有效时，优先级：transform > path > 直接取值）：
      transform: 若提供，调用 transform(state_value) 得到字段值（适合复杂提取）
      path:      若提供，按点路径遍历 state_value（如 "identity.verified"）
      否则：     直接使用 state_value 本身
    """
    description: str = ""              # 字段说明，注入评估 message 供 LLM 参考
    state_key: str | None = None       # 自动抽取源（state 中的 key）
    path: str | None = None            # 点路径（在 state_value 内遍历）
    transform: Callable[[Any], Any] | None = None  # 自定义提取函数
```

> **向后兼容**：`FieldSource` 保留为 `FieldDefinition` 的别名，旧代码无需修改。

### 3.3 StageDefinition — 阶段定义

```python
@dataclass
class StageDefinition:
    id: str
    name: str
    description: str
    output_schema: type[BaseModel] | None = None
    reference_file: str | None = None   # references/ 下的文件名
    tools: list[str] = field(default_factory=list)  # 该阶段期望使用的工具；before_tool_stage_guard 据此识别越级调用
    fields: dict[str, FieldDefinition] = field(default_factory=dict)
    checkpoint: bool = False            # 完成后触发持久化
    delta_state_keys: list[str] = field(default_factory=list)  # 额外快照的 state key
```

### 3.4 FlowEvalResult — 评估结果

```python
@dataclass
class FlowEvalResult:
    """完整评估结果"""

    flow_id: str
    skill_name: str
    is_done: bool
    current_stage: StageDefinition | None = None
    stage_evaluations: list[StageEvaluation] = field(default_factory=list)
    state_delta: dict[str, Any] = field(default_factory=dict)
    available_checkpoints: list[dict[str, Any]] = field(default_factory=list)

    # 向后兼容：completed_stages 从 stage_evaluations 派生
    @property
    def completed_stages(self) -> list[dict[str, Any]]: ...
```

### 3.5 FieldStatus — 单字段评估状态

```python
@dataclass
class FieldStatus:
    """单字段评估状态"""
    status: Literal["collected", "missing", "error"]
    value: Any = None           # collected 时有值
    description: str = ""       # missing 时的提示
    error: str = ""             # error 时的错误信息
```

### 3.6 StageEvaluation — 单阶段评估结果

```python
@dataclass
class StageEvaluation:
    """单阶段评估结果"""
    id: str
    name: str
    status: Literal["completed", "in_progress", "pending"]
    fields: dict[str, FieldStatus] | None = None  # in_progress 时有值
```

### 3.7 FlowEvaluatorRegistry — 全局注册表

```python
class FlowEvaluatorRegistry:
    """全局单例注册表，skill 标识 → evaluator 实例映射。

    标识策略：以 evaluator.skill_name（短名）为主键；
    注册时若提供 namespace（如 "insurance"），同时登记
    "{namespace}.{skill_name}" 别名，使 SkillEntry.id 全名也能命中。
    """
    _registry: dict[str, BaseFlowEvaluator] = {}

    @classmethod
    def register(cls, evaluator, *, namespace=None): ...

    @classmethod
    def get(cls, skill_name) -> BaseFlowEvaluator | None: ...

    @classmethod
    def values(cls) -> list[BaseFlowEvaluator]: ...  # 去重
```

---

## 4. FlowCallbacks — 三个生命周期 Hook

```python
class FlowCallbacks:
    def __init__(self, sessions_dir: Path, ttl_hours: int = 72,
                 skill_loader: SkillLoader | None = None): ...

    # Hook 1: before_model — 每轮 LLM 调用前
    async def before_model_flow_eval(self, ctx, *, turn, messages, **_): ...

    # Hook 2: before_tool — 工具执行前
    async def before_tool_stage_guard(self, ctx, *, turn, tool_calls, **_): ...

    # Hook 3: after_agent — 整个 run 结束后
    async def persist_flow_context(self, ctx, *, response): ...
```

### 4.1 before_model_flow_eval

每轮 LLM 调用前自动运行，核心流程：

1. **确定 evaluator**：优先 `_flow_context.skill_name`，其次 `_turn_matched_skills` 反查 Registry
2. **Pending task 检测**：无 `flow_id` 时直检 `TaskRegistry.list_active()`，将结果以 JSON 数组注入 system message
3. **初始化 flow_id**：首次调用且无 pending 时，通过 `TaskRegistry.generate_flow_id()` 生成短 ID
4. **运行评估**：调用 `evaluator.evaluate(flow_ctx, state)`
   - 内部完成字段抽取、Pydantic 校验、自动提交
   - 校验失败时把 `FieldStatus.error` 写进当前 stage 的 `fields_status`，由提示词暴露
5. **写入 state**：`state_delta`（含 `_flow_context.current_stage`）通过 `apply_delta()` 点路径合并
6. **注入评估消息**：评估结果（`FlowEvalResult`）作为独立 `role="system"` message 注入，结构化 JSON 格式
7. **注入提示词**：当前阶段 reference

### 4.2 before_tool_stage_guard

工具执行前检查越级调用：

1. 仅在 `_flow_context.current_stage` 存在且非 `__completed__` 时生效。
2. 计算下游 stage 的 `tools` 并集（`future_tools`）。
3. 任一 `tool_call.name ∈ future_tools` → 合成 `ToolLoopAction.STOP` 工具结果（含固定话术），通过 `HookAction.OVERRIDE` 替换 runner 的工具执行批次，复用 `_tool_phase` 的 STOP 收尾路径直接返回用户。
4. 不在任何 stage `tools` 中的工具视为通用工具（`collect_user_fields` / `resume_task` / `rollback_flow_stage` / `read_skill` / memory 等），始终放行。

### 4.3 persist_flow_context

整个 run 结束后持久化：

1. 调用 `evaluator.get_persistable_context(flow_ctx)` 输出扁平 snapshot。
2. **Checkpoint 检查**：仅最后完成阶段标记了 `checkpoint=True` 时写盘。
3. `__completed__` 时始终写盘（触发 TaskRegistry 自动删除记录）。
4. 每次写盘重渲染 `task_name`。

---

## 5. Reference 动态注入

### 5.1 加载策略

| 条件 | 加载模式 | 注入路径 |
|------|---------|---------|
| SKILL 无 `references/` 目录 | 无注入 | — |
| SKILL 有 `references/`，无 flow evaluator | FULL（全量） | `SkillLoader._append_references_full()` |
| SKILL 有 `references/` + flow evaluator 已注册 | Dynamic（按阶段） | `FlowCallbacks._build_stage_reference_block()` |

### 5.2 判断机制

`SkillLoader._load_skill_file()` 加载 SKILL.md 时，调用 `_is_flow_managed(skill_id)` 判断：

```python
def _is_flow_managed(self, skill_id: str) -> bool:
    """skill 是否被 FlowEvaluatorRegistry 接管。
    同时检查短名和全名（带 agent_id 前缀），与 Registry 的别名机制对齐。
    """
    from ..flow.base_evaluator import FlowEvaluatorRegistry
    if FlowEvaluatorRegistry.get(skill_id) is not None:
        return True
    if self.config.agent_id:
        full_id = f"{self.config.agent_id}.{skill_id}"
        if FlowEvaluatorRegistry.get(full_id) is not None:
            return True
    return False
```

- **flow-managed skill**：`_is_flow_managed` 返回 True，跳过全量追加，由 `before_model_flow_eval` 按当前阶段动态注入
- **普通 skill**：全量追加所有 reference 文件

### 5.3 Dynamic 注入路径

`FlowCallbacks._build_stage_reference_block()` 在 before_model hook 中统一注入：

1. 从 `evaluator.stages` 中找到当前阶段的 `StageDefinition.reference_file`
2. 通过 `skill_loader.get_skill()` 定位 SKILL 目录的 `path`
3. 读取 `path/references/<reference_file>`（复用 `_read_reference_file` 的 lru_cache）
4. 注入到 system message：`### 当前阶段参考: {stage_id}\n\n{content}`

---

## 6. LLM 可调用工具

### 6.1 CollectUserFieldsTool

将用户提供的字段写入当前阶段的暂存区。框架自动推断当前阶段（无需 stage_id）。**本工具仅做写入，不做校验**；字段有效性由下一轮 `evaluate()` 统一评估：

```python
class CollectUserFieldsTool(AgentTool):
    name = "collect_user_fields"
    description = "向当前流程阶段提交用户提供的信息。"
    # 参数: fields (object, required) — 字段键值对
```

**写入目标**：`session.state["_flow_context"]["_user_input_{stage_id}"]`
- 有 `state_key` 的字段由 evaluator 自动从 `session.state` 抽取，无需 LLM 调用本工具
- 无 `state_key` 的字段必须通过本工具提交
- 同一阶段多次调用会合并（而非覆盖）已提交的字段

### 6.2 RollbackFlowStageTool

回退到指定 checkpoint 阶段，清除目标及后续所有阶段数据：

```python
class RollbackFlowStageTool(AgentTool):
    name = "rollback_flow_stage"
    # 参数: stage_id (string, required) — 必须从 available_checkpoints 中取值
```

### 6.3 ResumeTaskTool

恢复或废弃中断流程：

```python
class ResumeTaskTool(AgentTool):
    name = "resume_task"
    # 参数: flow_id (string, required), action (enum["resume", "discard"], default="resume")
```

---

## 7. 上下文数据结构

### 7.1 `_flow_context` 运行时格式

```python
session.state["_flow_context"] = {
    "flow_id": "260420-a1b2",
    "skill_name": "withdraw_money_flow",

    # 用户输入暂存区（collect_user_fields 写入，evaluate 提交后清理）
    "_user_input_plan_confirm": {"confirmed": True, "selected_option": {...}},

    # 各阶段数据（evaluate 自动提交后写入）
    "stage_identity_verify": {"user_id": "U001", "id_card_verified": True, "policy_ids": [...]},
    "stage_identity_verify_delta": {"_customer_info_result": {...}, "_policy_query_result": {...}},

    "stage_options_query": {"available_options": [...], ...},
    "stage_options_query_delta": {"_rule_engine_result": {...}},

    "stage_plan_confirm": {"confirmed": True, "selected_option": {...}, "amount": 2000.0},
    "stage_plan_confirm_delta": {"_plan_allocations": [...]},

    # checkpoint 历史
    "checkpoints": [
        {"stage_id": "plan_confirm", "name": "方案确认", "description": "..."},
    ],
}
```

### 7.2 state_delta 点路径合并

```python
# ✅ 正确：点路径格式，不整体替换父对象
metadata={"state_delta": {"_flow_context.stage_identity_verify": {...}}}

# ❌ 错误：整体替换 _flow_context，会清空其他阶段数据
metadata={"state_delta": {"_flow_context": {"stage_identity_verify": {...}}}}
```

### 7.3 active_tasks.json 持久化格式

```json
{
  "active_tasks": [
    {
      "flow_id": "260420-a1b2",
      "skill_name": "withdraw_money_flow",
      "task_name": "资金领取（2000元）任务",
      "current_stage": "execute",
      "last_session_id": "session_xxx",
      "updated_at": 1744444900000,
      "resume_ttl_hours": 72,
      "flow_context_snapshot": {
        "flow_id": "260420-a1b2",
        "current_stage": "execute",
        "stages": {
          "identity_verify": {
            "status": "completed",
            "data": {"user_id": "U001", ...},
            "delta": {"_customer_info_result": {...}, ...}
          },
          "options_query": {"status": "completed", "data": {...}, "delta": {...}},
          "plan_confirm": {"status": "completed", "data": {...}, "delta": {...}},
          "execute": {"status": "pending", "data": {}, "delta": {}}
        }
      }
    }
  ]
}
```

---

## 8. Pending Task 检测

### 8.1 检测机制

每轮 `before_model_flow_eval` 直检 `TaskRegistry.list_active()`：

- 用户做决定前：JSON 提示持续可见
- 用户选择 discard：`resume_task` 删除记录 + 清空 `_flow_context`
- 用户选择 resume：`resume_task` 还原 `_flow_context`
- 下一轮自然不再触发

### 8.2 提示词格式

以 JSON 数组形式注入 system message：

```json
[
  {
    "task_name": "资金领取（2000元）任务",
    "flow_id": "260420-a1b2",
    "current_stage": "execute",
    "last_runtime": "2026-04-20 14:30:00"
  }
]
```

---

## 9. 执行流程详解

### 9.1 新建流程（取款示例）

```
1. 用户说"我要取钱"
2. SkillMatcher 匹配到 withdraw_money_flow SKILL
3. before_model_flow_eval:
   → _flow_context 为空
   → TaskRegistry 检测无待恢复任务
   → 初始化: {flow_id: "260420-a1b2", skill_name: "withdraw_money_flow"}
   → evaluate() → 抽取字段 → identity_verify 全字段就绪 → 自动提交
   → current_stage = options_query
   → 注入评估结果 JSON + options_query.md reference
4. LLM 按 SOP 调用 rule_engine
5. 下一轮 before_model_flow_eval:
   → evaluate() → options_query 全字段就绪 → 自动提交
   → current_stage = plan_confirm
   → 注入评估结果 JSON（含 user_required_fields: confirmed, selected_option, amount）
6. LLM 向用户确认方案后调用 collect_user_fields(fields={confirmed: true, ...})
   → 写入 _user_input_plan_confirm 暂存区
7. 下一轮 before_model_flow_eval:
   → evaluate() → 从暂存区读取用户字段 → plan_confirm 全字段就绪 → 自动提交
   → current_stage = double_confirm
8. LLM 向用户二次确认后调用 collect_user_fields(fields={double_confirm: true})
   → 写入 _user_input_double_confirm 暂存区
9. 下一轮 before_model_flow_eval:
   → evaluate() → double_confirm 全字段就绪 → 自动提交
   → current_stage = execute
   → 注入 execute.md reference
10. LLM 调用 submit_withdrawal
11. 下一轮 before_model_flow_eval:
    → evaluate() → execute 全字段就绪 → 自动提交
    → is_done=True → __completed__
12. persist_flow_context: __completed__ → TaskRegistry 自动删除记录
```

### 9.2 跨会话恢复

```
1. 用户新会话说"我要取钱"
2. before_model_flow_eval:
   → _flow_context 为空
   → TaskRegistry 检测到未完成任务（execute 阶段）
   → 注入 pending task JSON 列表
3. LLM 向用户展示未完成任务，等待确认
4. 用户选择继续 → LLM 调用 resume_task(flow_id="260420-a1b2", action="resume")
   → 还原 _flow_context（含 checkpoints 列表和 _user_input_ 暂存区）
   → 还原 _plan_allocations 等 delta 到 session.state 顶层
5. 下一轮 before_model_flow_eval:
   → evaluate() → 从 state + 暂存区抽取字段 → current_stage = execute
   → 注入评估结果 JSON + execute.md reference
6. LLM 按 execute 阶段 SOP 调用 submit_withdrawal
```

### 9.3 流程回退

```
1. 用户在 execute 阶段说"我想换一个方案"
2. before_model_flow_eval:
   → 提示词中显示 available_checkpoints: [plan_confirm]
3. LLM 判断意图匹配 plan_confirm → 告知用户将回退
4. 用户确认 → LLM 调用 rollback_flow_stage(stage_id="plan_confirm")
   → 清除 stage_plan_confirm、stage_plan_confirm_delta
   → 清除 stage_double_confirm、stage_double_confirm_delta
   → 清除 stage_execute、stage_execute_delta
   → _flow_context.checkpoints 移除 plan_confirm 记录
5. 下一轮 before_model_flow_eval:
   → current_stage = plan_confirm
   → 重新展示方案，收集用户确认
```

---

## 10. 日志体系

框架在关键节点输出结构化日志，便于追踪流程状态：

| 日志标签 | 级别 | 输出位置 | 示例 |
|---------|------|---------|------|
| `[FlowEval]` | INFO | `evaluate()` | `skill=withdraw_money_flow flow_id=260420-a → stage=plan_confirm (方案确认) progress=2/5` |
| `[FlowEval]` | INFO | `evaluate()` | `skill=withdraw_money_flow flow_id=260420-a → auto-committed stage=identity_verify (身份核验)` |
| `[FlowEval]` | WARNING | `evaluate()` | `skill=withdraw_money_flow flow_id=260420-a → stage=plan_confirm blocked (validation failed): [...]` |

---

## 11. task_name 模板渲染

`BaseFlowEvaluator.task_name_template` 支持从已完成阶段数据动态渲染任务名：

```python
# 业务层覆写
@property
def task_name_template(self) -> str:
    return "资金领取（{amount:.0f}元）任务"

# 渲染规则
# - 命名空间：已完成阶段 data 展平 < flow_ctx 顶层键（后者胜出）
# - 缺失变量渲染为 "{待定}"（_Missing.__format__ 处理任意 format_spec）
# - 渲染失败时降级为 skill_name
```

**渲染时机**：每次 `persist_flow_context` 写盘时重新渲染，阶段推进后模板中的 `{待定}` 会被已提交的阶段数据替换。

---

## 12. 文件清单

```
src/ark_agentic/
├── core/
│   ├── flow/
│   │   ├── __init__.py              # 模块导出
│   │   ├── base_evaluator.py        # BaseFlowEvaluator(ABC) + FieldDefinition + FieldStatus
│   │   │                            # + StageEvaluation + StageDefinition + FlowEvalResult
│   │   │                            # + FlowEvaluatorRegistry + task_name_template / render_task_name
│   │   ├── callbacks.py             # FlowCallbacks: 2 个 Hook
│   │   │                            #   before_model_flow_eval / persist_flow_context
│   │   │                            #   + _build_stage_reference_block (Dynamic reference 注入)
│   │   ├── collect_user_fields.py   # CollectUserFieldsTool（仅写入暂存区）
│   │   ├── rollback_flow_stage.py   # RollbackFlowStageTool（回退到 checkpoint 阶段）
│   │   └── task_registry.py         # TaskRegistry（active_tasks.json + generate_flow_id）
│   ├── tools/
│   │   └── resume_task.py           # ResumeTaskTool（resume/discard）
│   ├── skills/
│   │   └── loader.py                # SkillLoader._is_flow_managed() 判断加载模式
│   └── runner.py                    # _read_reference_file(lru_cache)
│
└── agents/insurance/
    ├── agent.py                     # FlowEvaluatorRegistry.register(namespace="insurance")
    │                                # FlowCallbacks 注入 RunnerCallbacks
    ├── tools/
    │   ├── flow_evaluator.py        # WithdrawalFlowEvaluator（5 阶段 + task_name_template）
    │   └── __init__.py              # create_insurance_tools() 不含 evaluator
    └── skills/withdraw_money_flow/
        ├── SKILL.md                 # required_tools 不含 evaluator/commit_flow_stage
        └── references/              # Dynamic 模式，按阶段注入
            ├── identity_verify.md
            ├── options_query.md
            ├── plan_confirm.md
            ├── double_confirm.md
            └── execute.md
```

---

## 13. 关键设计决策

### D1: 统一评估点（evaluate() 单路径）

Evaluator 由 `FlowCallbacks` 的两个 Hook 自动驱动，所有评估与提交统一在 `evaluate()` 方法内完成。理由：
- 避免依赖 LLM 主动调用评估器，确保流程状态始终同步
- 单路径设计消除 `auto_commit_tool_stages()` 与 `CollectUserFieldsTool.execute()` 双提交入口的竞态和复杂度
- `_commit_stage()` 作为唯一提交入口，仅在 `evaluate()` 的 stage 循环内被调用，禁止其他位置调用
- `collect_user_fields` 仅写入暂存区，不做校验，降低 LLM 工具复杂度

### D2: Pending Task 检测每轮直检 Registry

每轮直接读 `TaskRegistry.list_active()`，无短路标记。理由：用户可能在后续轮才决定 resume/discard，每轮直检确保 JSON 提示持续可见，做完决定后下一轮自然不再触发。

### D3: Reference 单一注入路径

flow-managed skill 的 reference 统一由 `FlowCallbacks._build_stage_reference_block()` 在 before_model hook 中按当前阶段注入。`SkillLoader._is_flow_managed()` 判断有 evaluator 的 SKILL 跳过全量追加，避免重复加载。

### D4: Checkpoint 写盘策略

仅在最后完成的阶段标记了 `checkpoint=True` 时写盘。`__completed__` 时始终写盘触发清理。非 checkpoint 阶段不写盘（如 `options_query` 可重新执行）。

### D5: discard 时清空 _flow_context

`_handle_discard` 返回 `state_delta: {"_flow_context": {}}`，防止 `persist_flow_context` 在本轮 after_agent 阶段把刚删除的任务记录重新写回。

### D6: task_name_template 动态渲染

每次 `persist_flow_context` 写盘时重新渲染，阶段推进后模板中原本的 `{待定}` 会被已提交的阶段数据替换为具体值（如金额）。`_Missing.__format__` 处理任意 format_spec（如 `{amount:.0f}`），避免类型差异导致 ValueError。

### D7: 短 flow_id 生成

`TaskRegistry.generate_flow_id()` 生成 `YYMMDD-HHHH` 格式（日期前缀 + 4位hex），per-user 查重，碰撞时重试最多 8 次后扩至 8 位 hex。比纯 UUID 更利于日志排查和人工检索。

### D8: 阻断机制（仅拦截越级调用）

阻断不再发生在 `before_model`，也不再依赖 `block_model`。`FlowCallbacks.before_tool_stage_guard`（`before_tool` hook）只在「当前 stage 未完成 + LLM 调用了某个下游 stage 的 `tools` 工具」时合成 `ToolLoopAction.STOP` 工具结果，复用 runner `_tool_phase` 已有的 STOP 收尾路径，向用户输出固定话术「当前流程阶段「XX」尚未完成，请先按提示完成本阶段后再继续。」。

字段缺失 / Pydantic 校验失败由 `FieldStatus.missing|error` 在 Flow Evaluation 提示词里暴露，模型自然继续推进收集，不再触发"刹车"。理由：
- 数据缺失/校验失败属于业务正常分支，给模型上下文比硬阻断更利于自我修复。
- "越级调用下游工具" 才是真正会造成不可逆事故的越界，必须立即截断。
- 复用 `ToolLoopAction.STOP` 一套 loop 终结机制，不引入第二套 `block_model` 路径，保留设计一致性。
