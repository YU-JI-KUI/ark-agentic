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
  → state_delta 写入 _flow_stage
    → 框架自动注入当前阶段 reference
      → Agent 按 SOP 执行业务工具（结果写入 session.state）
        → Agent 调用 commit_flow_stage(stage_id, user_data)
            → 框架按 field_sources 自动提取 tool 来源字段
            → LLM 提供 user 来源字段（via user_data）
            → Pydantic 校验通过 → 写入 _flow_context.stage_<id>
          → flow_evaluator 再评估（Pydantic 校验通过 → 进入下一阶段）
```

---

## 2. 核心组件设计

### 2.1 SKILL 结构与 Reference 定义

`references/` 是 SKILL 目录下的**可选子目录**，与 `SKILL.md` 同级。`SKILL.md` 的 frontmatter 中不再声明 `references:` 索引，reference 文档通过正文中的相对路径直接引用。

**目录结构**：

```
skills/withdraw_money/
├── SKILL.md                  # 主 SKILL 文件
└── references/               # 可选：阶段 SOP 文档
    ├── identity_verify.md
    ├── options_query.md
    ├── plan_confirm.md
    └── execute.md
```

**SKILL.md frontmatter 示例**：

```yaml
required_tools: [flow_evaluator, identity_service, fund_service, resume_task]
```

**SKILL.md 正文示例**（无需显式引用 reference，框架自动注入）：

```markdown
## 执行步骤
1. 首先调用 flow_evaluator 评估当前阶段
2. 根据当前阶段参考文档中的操作指引，使用对应工具完成当前阶段
3. 调用 flow_evaluator 确认阶段完成，进入下一阶段
```

* **存储约定**：在 SKILL 目录下建立 `references/` 子目录存放具体的 `.md` 阶段 SOP 文档。
* **加载行为**：框架根据 `_flow_stage` 自动注入对应 reference，SKILL 对此完全透明。

---

### 2.2 流程评估工具 (FlowEvaluator) — 基类 + 业务继承模式

**这是最核心的变更**。框架层提供 `BaseFlowEvaluator` 抽象基类，每个业务流程继承它并仅需定义阶段列表，本质是一个**确定性状态机**包装为 AgentTool：

```python
from dataclasses import dataclass, field
from abc import ABC, abstractmethod
from typing import Any
from pydantic import BaseModel, ValidationError


# ── Pydantic Schema 定义（每阶段的完成条件）──

class IdentityVerifyOutput(BaseModel):
    """身份核验阶段的完成数据"""
    user_id: str
    id_card_verified: bool
    policy_ids: list[str]

class OptionsQueryOutput(BaseModel):
    """方案查询阶段的完成数据"""
    available_options: list[dict]
    total_cash_value: float
    max_withdrawal: float

class PlanConfirmOutput(BaseModel):
    """方案确认阶段的完成数据"""
    confirmed: bool
    selected_option: dict
    amount: float

class ExecuteOutput(BaseModel):
    """执行阶段的完成数据"""
    transaction_id: str
    status: str  # "submitted" | "pending" | "failed"


# ── 阶段定义 ──

@dataclass
class FieldSource:
    """阶段 schema 字段的数据来源声明，供 CommitFlowStageTool 使用。

    source="tool": 框架从 session.state[state_key] 自动提取，LLM 无需传值。
    source="user": LLM 必须通过 commit_flow_stage(user_data=...) 明确提供。

    提取逻辑（source="tool" 时，优先级：transform > path > 直接取值）：
      transform: 调用 transform(state_value) 得到字段值（适合复杂提取/列表推导）
      path:      按点路径遍历 state_value（如 "identity.verified"）
      否则：     直接使用 state_value 本身
    """
    source: Literal["tool", "user"] = "user"
    state_key: str | None = None   # 读取哪个 session.state key
    path: str | None = None        # 点路径（如 "identity.verified"）
    transform: Callable | None = None  # 复杂提取逻辑，优先于 path


@dataclass
class StageDefinition:
    """阶段定义

    required 行为约定：
      - True（默认）：必须阶段，无数据时阻塞后续阶段，_evaluate_stages 将其视为当前阶段。
      - False：可跳过阶段，无数据时 status="skipped"，不阻塞后续阶段推进。

    field_sources 行为约定：
      声明每个 output_schema 字段的数据来源（tool 或 user）。
      source="tool"：框架自动从 session.state 提取。
      source="user"：LLM 需从用户对话收集，evaluator 响应中自动列出待收集字段及说明。
      CommitFlowStageTool 依此决定哪些字段自动提取、哪些要求 LLM 提供。
      未声明 field_sources 时，CommitFlowStageTool 直接使用 user_data（兼容旧阶段）。
    """
    id: str
    name: str
    description: str
    required: bool = True
    output_schema: type[BaseModel] | None = None
    reference_file: str | None = None  # references/ 目录下的文件名，如 "identity_verify.md"
                                       # Dynamic 模式注入时以此为准，与 stage.id 解耦
    tools: list[str] = field(default_factory=list)
    field_sources: dict[str, FieldSource] = field(default_factory=dict)

    def validate_output(self, data: dict) -> tuple[bool, list[str]]:
        """用 Pydantic 校验阶段输出数据"""
        if not self.output_schema:
            return True, []
        try:
            self.output_schema(**data)
            return True, []
        except ValidationError as e:
            return False, [str(err) for err in e.errors()]


# ── FlowEvaluatorRegistry（框架层，位于 core/flow/base_evaluator.py）──
# 解决 persist_flow_context hook 需要通过 skill_name 字符串反查 evaluator 实例的问题。

class FlowEvaluatorRegistry:
    """全局单例注册表，维护 skill_name → evaluator 实例的映射。
    
    业务层在初始化 Agent 时通过 register() 注册；
    框架层的 persist_flow_context callback 通过 get() 反查，无需硬编码 import。
    """
    _registry: dict[str, "BaseFlowEvaluator"] = {}

    @classmethod
    def register(cls, evaluator: "BaseFlowEvaluator") -> None:
        cls._registry[evaluator.skill_name] = evaluator

    @classmethod
    def get(cls, skill_name: str) -> "BaseFlowEvaluator | None":
        return cls._registry.get(skill_name)


# ── BaseFlowEvaluator 抽象基类（框架层，位于 core/flow/base_evaluator.py）──

class BaseFlowEvaluator(AgentTool, ABC):
    """流程评估器基类（框架层）
    
    每个业务流程继承此类，实现自己的阶段定义和校验逻辑。
    基类提供通用的阶段遍历、Pydantic 校验、状态恢复等能力。
    """
    description = "评估当前流程进度，返回当前阶段、已完成步骤、下一步操作建议"

    @property
    def name(self) -> str:
        """工具名称与 skill_name 绑定，避免多流程并存时 name 冲突。
        
        若 Agent 同时注册了 WithdrawalFlowEvaluator 和 LoanFlowEvaluator，
        name 分别为 "withdrawal_flow_evaluator" / "loan_flow_evaluator"，不会冲突。
        SKILL.md frontmatter 中 required_tools 需写对应具体名称，如 "withdrawal_flow_evaluator"。
        """
        return f"{self.skill_name}_evaluator"

    @property
    @abstractmethod
    def stages(self) -> list[StageDefinition]:
        """子类必须定义阶段列表"""
        ...

    @property
    @abstractmethod
    def skill_name(self) -> str:
        """子类必须声明关联的 SKILL 名称（同时作为工具 name 的前缀）"""
        ...

    async def execute(self, tool_call, context=None):
        """通用执行逻辑：阶段遍历 + Pydantic 校验 + 指引生成"""
        flow_ctx = (context or {}).get("_flow_context", {})
        completed, is_done = self._evaluate_stages(flow_ctx)

        # ── 所有阶段均通过校验：流程完成 ──
        if is_done:
            return AgentToolResult(
                result_type=ToolResultType.JSON,
                content={
                    "flow_status": "completed",
                    "completed_stages": completed,
                    "progress": f"{len(self.stages)}/{len(self.stages)}",
                    "instruction": "所有阶段已完成，流程结束。",
                },
                metadata={"state_delta": {"_flow_stage": "__completed__"}},
            )

        # ── 找到第一个未完成阶段 ──
        current_stage = self.stages[len(completed)]
        # 若阶段含 source="user" 字段，在响应中列出，由模型自主规划收集
        user_fields = current_stage.user_required_fields()
        current_stage_info = {
            "id": current_stage.id,
            "name": current_stage.name,
            "description": current_stage.description,
            "suggested_tools": current_stage.tools,
        }
        if user_fields:
            current_stage_info["user_required_fields"] = user_fields
        return AgentToolResult(
            result_type=ToolResultType.JSON,
            content={
                "flow_status": "in_progress",
                "current_stage": current_stage_info,
                "completed_stages": completed,
                "progress": f"{len(completed)}/{len(self.stages)}",
                "instruction": self._build_instruction(current_stage),
            },
            metadata={"state_delta": {"_flow_stage": current_stage.id}},
        )

    def _evaluate_stages(
        self, flow_ctx: dict
    ) -> tuple[list[dict], bool]:
        """遍历阶段，返回 (已完成阶段列表, 是否全部完成)。
        
        required=False 的阶段在无数据时视为已跳过（status="skipped"），
        不阻塞后续阶段推进。
        """
        completed = []
        for stage in self.stages:
            stage_data = flow_ctx.get(f"stage_{stage.id}", {})
            if not stage_data:
                if not stage.required:
                    completed.append({"id": stage.id, "name": stage.name, "status": "skipped"})
                    continue
                # 必须阶段无数据 → 即为当前阶段，停止遍历
                break
            valid, errors = stage.validate_output(stage_data)
            if valid:
                completed.append({"id": stage.id, "name": stage.name, "status": "completed"})
            else:
                completed.append({"id": stage.id, "name": stage.name, "status": "incomplete", "errors": errors})
                break  # 校验失败 → 当前阶段，停止遍历
        
        is_done = len(completed) == len(self.stages)
        return completed, is_done

    def _determine_current_stage(self, flow_ctx: dict) -> StageDefinition | None:
        """返回第一个未完成的阶段；若全部完成返回 None。"""
        _, is_done = self._evaluate_stages(flow_ctx)
        if is_done:
            return None
        completed, _ = self._evaluate_stages(flow_ctx)
        return self.stages[len(completed)]

    def _build_instruction(self, stage: StageDefinition) -> str:
        user_fields = stage.user_required_fields()
        if user_fields:
            field_names = ", ".join(f["field"] for f in user_fields)
            return (
                f"当前处于【{stage.name}】阶段。"
                f"请按参考文档完成准备工作（{stage.tools}），"
                f"向用户收集以下信息：{field_names}，"
                f"然后调用 commit_flow_stage 提交，再次调用 {self.name} 确认推进。"
            )
        return (
            f"当前处于【{stage.name}】阶段。"
            f"请根据当前阶段参考文档中的操作指引，"
            f"使用 {stage.tools} 完成此阶段。"
        )

    def get_restorable_state(self, flow_ctx: dict) -> dict:
        return {
            "flow_id": flow_ctx.get("flow_id"),
            "skill_name": self.skill_name,
            "current_stage": self._determine_current_stage(flow_ctx).id,
            "stages": {
                stage.id: {
                    "status": "completed" if self._is_stage_complete(stage, flow_ctx) else "pending",
                    "data": flow_ctx.get(f"stage_{stage.id}", {}),
                }
                for stage in self.stages
            },
        }

    def _is_stage_complete(self, stage: StageDefinition, flow_ctx: dict) -> bool:
        stage_data = flow_ctx.get(f"stage_{stage.id}", {})
        if not stage_data:
            return False
        valid, _ = stage.validate_output(stage_data)
        return valid


# ── WithdrawalFlowEvaluator（业务层，位于 agents/insurance/tools/flow_evaluator.py）──

class WithdrawalFlowEvaluator(BaseFlowEvaluator):
    """保险取款流程评估器（业务层实现）

    继承框架基类，仅需定义：
    1. stages: 阶段列表、Pydantic schema 和 field_sources
    2. skill_name: 关联的 SKILL 名称
    """

    @property
    def skill_name(self) -> str:
        return "withdraw_money_flow"

    @property
    def stages(self) -> list[StageDefinition]:
        return [
            StageDefinition(
                id="identity_verify",
                name="身份核验",
                output_schema=IdentityVerifyOutput,
                reference_file="identity_verify.md",
                tools=["customer_info", "policy_query"],
                field_sources={
                    # user_id: customer_info 返回根路径 user_id，直接提取
                    "user_id": FieldSource("tool", "_customer_info_result", "user_id"),
                    # id_card_verified: 工具返回 identity.verified，字段名不同 + 嵌套路径
                    "id_card_verified": FieldSource("tool", "_customer_info_result", "identity.verified"),
                    # policy_ids: 从 policyAssertList 列表推导，需要 transform
                    "policy_ids": FieldSource("tool", "_policy_query_result",
                        transform=lambda r: [p["policy_id"] for p in r.get("policyAssertList", [])]),
                },
            ),
            StageDefinition(
                id="options_query",
                name="方案查询",
                output_schema=OptionsQueryOutput,
                reference_file="options_query.md",
                tools=["rule_engine"],
                field_sources={
                    # schema 字段名 vs 工具字段名均不同，通过 path 声明映射
                    "available_options": FieldSource("tool", "_rule_engine_result", "options"),
                    "total_cash_value":  FieldSource("tool", "_rule_engine_result", "total_available_excl_loan"),
                    "max_withdrawal":    FieldSource("tool", "_rule_engine_result", "total_available_incl_loan"),
                },
            ),
            StageDefinition(
                id="plan_confirm",
                name="方案确认",
                output_schema=PlanConfirmOutput,
                reference_file="plan_confirm.md",
                tools=["render_a2ui"],
                field_sources={
                    # 全部 user 来源：evaluator 在响应中列出 user_required_fields，由模型收集
                    "confirmed":       FieldSource("user", description="用户是否确认方案（true/false）"),
                    "selected_option": FieldSource("user", description="选中方案，含 channels 和 target"),
                    "amount":          FieldSource("user", description="最终取款金额（元）"),
                },
            ),
            StageDefinition(
                id="execute",
                name="执行取款",
                output_schema=ExecuteOutput,
                reference_file="execute.md",
                tools=["submit_withdrawal"],
                field_sources={
                    # submit_withdrawal 写入 _submitted_channels（渠道列表）
                    "submitted": FieldSource("tool", "_submitted_channels",
                        transform=lambda channels: bool(channels)),
                    "channels":  FieldSource("tool", "_submitted_channels"),
                },
            ),
        ]


# ── 业务层初始化时注册 evaluator（位于 agents/insurance/tools/__init__.py）──

_withdrawal_evaluator = WithdrawalFlowEvaluator()
FlowEvaluatorRegistry.register(_withdrawal_evaluator)
# Agent 同时将其加入 tools 列表，name = "withdraw_money_flow_evaluator"
```

---

### 2.2.1 CommitFlowStageTool — 阶段数据提交工具

**问题背景**：业务工具（`customer_info`、`rule_engine` 等）将结果写入各自的 state key（如 `_customer_info_result`），字段名和路径与阶段 schema 不一定一致，且部分字段来自用户对话而非工具调用。框架不能依赖 LLM 自行拼装 `state_delta` 写入 `_flow_context.stage_<id>`——LLM 无法控制工具返回的 `metadata["state_delta"]`。

**解决方案**：新增 `CommitFlowStageTool`（框架层，`core/flow/commit_flow_stage.py`），由 LLM 在完成阶段业务后显式调用。工具按 `StageDefinition.field_sources` 声明完成以下工作：

1. `source="tool"` 字段：从 `session.state[state_key]` 自动提取（支持点路径和 transform）
2. `source="user"` 字段：从 `user_data` 参数取值（要求 LLM 从对话上下文提供）
3. Pydantic 校验合并后的数据
4. 写入 `_flow_context.stage_<id>`（点路径，不覆盖同级 key）

```python
# 框架层工具（core/flow/commit_flow_stage.py）
class CommitFlowStageTool(AgentTool):
    name = "commit_flow_stage"
    description = "提交当前流程阶段的完成数据。框架自动提取 tool 来源字段，LLM 仅需提供 user 来源字段。"
    parameters = [
        ToolParameter("stage_id", "string", "阶段 ID", required=True),
        ToolParameter("user_data", "object", "用户来源字段", required=False),
    ]

    async def execute(self, tool_call, context=None):
        ctx = context or {}
        stage_id = args["stage_id"]
        user_data = args.get("user_data") or {}

        # 从 _flow_context 获取 skill_name，查找 evaluator 和 stage 定义
        skill_name = (ctx.get("_flow_context") or {}).get("skill_name", "")
        evaluator = FlowEvaluatorRegistry.get(skill_name)
        stage = next(s for s in evaluator.stages if s.id == stage_id)

        # 按 field_sources 声明收集数据
        collected = {}
        for field_name, fs in stage.field_sources.items():
            if fs.source == "tool":
                state_val = ctx[fs.state_key]
                collected[field_name] = fs.transform(state_val) if fs.transform \
                    else _dot_get(state_val, fs.path) if fs.path else state_val
            else:  # "user"
                collected[field_name] = user_data[field_name]

        # Pydantic 校验 → 写入 _flow_context.stage_<id>
        stage.validate_output(collected)  # raises on failure
        return AgentToolResult.json_result(...,
            metadata={"state_delta": {f"_flow_context.stage_{stage_id}": collected}})
```

**字段来源决策树**：

```
对于阶段的每个 schema 字段：
  ├── source="tool"
  │     ├── transform 有值 → transform(session.state[state_key])
  │     ├── path 有值     → 点路径遍历 session.state[state_key]
  │     └── 否则          → session.state[state_key] 直接赋值
  └── source="user"       → user_data[field_name]（LLM 必须提供）
```

---

---

### 2.3 Reference 框架级透明注入

Reference 的加载对 SKILL 完全透明——SKILL.md 不需要显式提及 reference 文件，框架根据加载模式自动处理。

#### FULL 模式（全量注入）

**注入点**：`SkillLoader._load_skill_file()` 加载 SKILL.md 时，自动扫描 `references/` 子目录。

```python
# SkillLoader._load_skill_file() 中新增逻辑
def _load_skill_file(self, file_path: Path, skill_id: str, priority: int) -> SkillEntry | None:
    content = file_path.read_text(encoding="utf-8")
    frontmatter, body = self._parse_frontmatter(content)
    
    # ★ 自动扫描并追加 references/ 目录下的所有 .md 文件
    references_dir = file_path.parent / "references"
    if references_dir.exists():
        body = self._append_references(body, references_dir)
    
    # ... 构建 SkillEntry ...

def _append_references(self, body: str, references_dir: Path) -> str:
    """自动扫描 references 目录，将内容追加到 SKILL body"""
    sections = [body]
    for ref_file in sorted(references_dir.glob("*.md")):
        ref_content = ref_file.read_text(encoding="utf-8")
        sections.append(f"\n\n---\n### Reference: {ref_file.stem}\n")
        sections.append(ref_content)
    return "\n".join(sections)
```

效果：SKILL body + 所有 reference 内容 → 合并为一个完整的 `SkillEntry.content` → `build_skill_prompt()` 渲染到 `<skill>` 标签 → Agent 看到的是一个完整的 SKILL 文档。

**适用场景**：reference 文件较少或内容较短的 SKILL。

#### Dynamic 模式（状态驱动按需注入）

**注入点**：`AgentRunner._build_system_prompt()` 构建 system prompt 时，读取 `session.state["_flow_stage"]`，仅注入当前阶段对应的 reference。

**`_flow_stage` 语义说明**：`_flow_stage` 存储的是当前阶段的 `stage.id`（字符串），由 `flow_evaluator` 通过 `state_delta` 写入。它是 reference 注入的**唯一来源**，与 `_evaluate_stages` 对 `_flow_context` 数据的校验保持一致——evaluator 每次执行都会重新推断当前阶段并更新 `_flow_stage`，两者不会长期不一致。

```python
# AgentRunner._build_system_prompt() 中新增逻辑
def _build_system_prompt(self, state, session_id=None, skill_load_mode="full"):
    # ... 现有的 skill matching 逻辑 ...
    
    # ★ 如果存在 _flow_stage（且非 __completed__），按阶段动态注入 reference
    current_stage_id = state.get("_flow_stage")
    if current_stage_id and current_stage_id != "__completed__" and skills:
        skills = self._enrich_skills_with_stage_reference(skills, current_stage_id)
    
    return SystemPromptBuilder.quick_build(...)

def _enrich_skills_with_stage_reference(
    self, skills: list[SkillEntry], current_stage_id: str
) -> list[SkillEntry]:
    """根据当前阶段 ID，查找对应 FlowEvaluator 的 reference_file 并注入。
    
    使用 StageDefinition.reference_file 字段（而非直接拼接 stage.id），
    避免 stage.id 与文件名不一致导致静默失败。
    """
    enriched = []
    for skill in skills:
        # 从注册表查找该 skill 对应的 evaluator
        evaluator = FlowEvaluatorRegistry.get(skill.skill_id)
        ref_filename = None
        if evaluator:
            stage_def = next(
                (s for s in evaluator.stages if s.id == current_stage_id), None
            )
            ref_filename = stage_def.reference_file if stage_def else None
        
        if ref_filename:
            ref_path = Path(skill.path) / "references" / ref_filename
            if ref_path.exists():
                ref_content = ref_path.read_text(encoding="utf-8")
                enriched_skill = replace(
                    skill,
                    content=(
                        skill.content
                        + f"\n\n---\n### 当前阶段参考: {current_stage_id}\n"
                        + ref_content
                    ),
                )
                enriched.append(enriched_skill)
                continue
            else:
                # reference_file 有配置但文件不存在，发出警告而非静默跳过
                import warnings
                warnings.warn(
                    f"[FlowEvaluator] reference file not found: {ref_path}",
                    stacklevel=2,
                )
        enriched.append(skill)
    return enriched
```

**执行流程**：
```
flow_evaluator 执行
  → _evaluate_stages() 推断当前阶段
  → state_delta 写入 _flow_stage = "identity_verify"
  → 下一轮 _build_system_prompt() 检测到 _flow_stage
  → FlowEvaluatorRegistry.get(skill_id) 查找 evaluator
  → 从 StageDefinition.reference_file 获取文件名（如 "identity_verify.md"）
  → 读取 references/identity_verify.md 追加到 SkillEntry.content
  → Agent 自动获得当前阶段的 SOP 指引
  → 阶段切换时，下一轮自动切换 reference 内容
```

**适用场景**：多阶段流程（如取款4步 SOP），每个阶段的 reference 内容较大。

#### 模式选择策略

| 条件 | 使用模式 | 原因 |
|------|---------|------|
| SKILL 无 references/ 目录 | 无注入 | 普通 SKILL |
| SKILL 有 references/，无 FlowEvaluator | FULL | 一次性加载所有参考文档 |
| SKILL 有 references/ + FlowEvaluator 设置了 _flow_stage | Dynamic | 按阶段按需加载，节省 token |

注意：两种模式可自动判断——当 `session.state` 中存在 `_flow_stage` 时使用 Dynamic 模式，否则使用 FULL 模式。无需配置。

---

### 2.4 上下文管理与 `state_delta`

* **共享内存**：在 `session.state` 中预留 `_flow_context` 字段。
* **增量更新**：业务工具执行完成后，通过 `metadata.state_delta` 写入结果。
* **数据隔离**：`_flow_context` 使用 `_` 前缀命名，约定为流程内部专用字段，避免被其他工具意外覆盖。

**_flow_context 内部结构约定**：

```python
session.state["_flow_context"] = {
    "flow_id": "uuid-xxx",              # 流程实例 ID
    "skill_name": "withdrawal_flow",     # 关联的 SKILL 名称
    "started_at": 1744444800000,         # 开始时间（毫秒时间戳）
    
    # 各阶段数据（由业务工具的 state_delta 逐步写入）
    "stage_identity_verify": {
        "user_id": "U001",
        "id_card_verified": True,
        "policy_ids": ["POL001", "POL002"],
    },
    "stage_options_query": {
        "available_options": [...],
        "total_cash_value": 150000.0,
        "max_withdrawal": 120000.0,
    },
    # stage_plan_confirm, stage_execute 在后续阶段填充
}
```

**工具写入约定**：业务工具通过 `state_delta` 写入阶段数据，**必须使用点路径（dot-path）格式**，
key 为 `_flow_context.stage_{stage_id}`，值为该阶段的完整 dict。

框架的 `state_delta` 处理器须实现**深度合并（deep merge）**：
- 对普通 key 执行 `dict.update()`
- 对以 `.` 分隔的路径 key 执行逐层合并，不整体替换父对象

```python
# ✅ 正确写法：路径写入，不依赖 **existing_flow_ctx 展开
return AgentToolResult(
    result_type=ToolResultType.JSON,
    content={"verified": True, ...},
    metadata={
        "state_delta": {
            # 点路径格式：框架自动深度合并到 session.state["_flow_context"]["stage_identity_verify"]
            "_flow_context.stage_identity_verify": {
                "user_id": "U001",
                "id_card_verified": True,
                "policy_ids": ["POL001"],
            },
        }
    },
)

# ❌ 错误写法：整体替换 _flow_context，会清空其他阶段数据
# metadata={"state_delta": {"_flow_context": {"stage_identity_verify": {...}}}}
```

> **框架实现要求**：`AgentRunner._apply_state_delta()` 需支持点路径合并。
> 若 key 包含 `.`，则按路径逐层 `setdefault({})` 后赋值，而非 `session.state.update(delta)`。

---

## 3. 持久化与跨会话恢复机制

为了解决"用户离开后任务丢失"的问题，在用户维度建立任务注册表。

### 3.1 任务注册表 (Task Registry)

* **文件路径**：`storage/{user_id}/active_tasks.json`
* **新增字段**：`flow_context_snapshot`（存储 `FlowEvaluator.get_restorable_state()` 的结果）、`resume_ttl_hours`（默认 72 小时）、`updated_at`（毫秒时间戳）

```json
{
  "active_tasks": [
    {
      "flow_id": "flow_uuid_123",
      "skill_name": "withdrawal_flow",
      "current_stage": "plan_confirm",
      "last_session_id": "session_20260412",
      "updated_at": 1744444900000,
      "resume_ttl_hours": 72,
      "flow_context_snapshot": {
        "stages": {
          "identity_verify": {"status": "completed", "data": {"user_id": "U001", "id_card_verified": true, "policy_ids": ["POL001"]}},
          "options_query": {"status": "completed", "data": {"available_options": [], "total_cash_value": 150000.0, "max_withdrawal": 120000.0}},
          "plan_confirm": {"status": "pending", "data": {}},
          "execute": {"status": "pending", "data": {}}
        }
      }
    }
  ]
}
```

### 3.2 持久化 Hook (after_agent)

新增 `after_agent` hook 实现持久化逻辑，相关回调函数属于**框架核心代码**，统一放在 `core/flow/callbacks.py` 中：

```python
async def persist_flow_context(context: CallbackContext) -> CallbackResult:
    """after_agent hook：持久化 _flow_context 到 active_tasks.json"""
    session = context.session
    flow_ctx = session.state.get("_flow_context")
    
    if not flow_ctx or not flow_ctx.get("flow_id"):
        return CallbackResult()  # 无活跃 flow，跳过
    
    user_id = session.state.get("user:id")
    if not user_id:
        return CallbackResult()
    
    # 从注册表反查 evaluator，获取可恢复状态
    evaluator = FlowEvaluatorRegistry.get(flow_ctx.get("skill_name", ""))
    if not evaluator:
        return CallbackResult()  # 未注册的 skill，跳过持久化
    restorable = evaluator.get_restorable_state(flow_ctx)
    
    # 写入 active_tasks.json
    task_registry = TaskRegistry(base_dir=SESSIONS_DIR)
    task_registry.upsert(
        user_id=user_id,
        flow_id=flow_ctx["flow_id"],
        skill_name=flow_ctx["skill_name"],
        current_stage=restorable["current_stage"],
        last_session_id=session.session_id,
        flow_context_snapshot=restorable,
    )
    
    return CallbackResult()
```

### 3.3 恢复路径 (Resumption Path)

**Step 1: 唤醒提示注入**

在新会话的 `before_agent` hook 中检查 `active_tasks.json`：

```python
async def inject_flow_hint(context: CallbackContext) -> CallbackResult:
    """before_agent hook：检查未完成任务并注入提示。
    
    注入路径：将 hint 写入 context.extra_system_instructions，
    框架的 SystemPromptBuilder 将其渲染到 system prompt 末尾的 <system_hint> 标签，
    Agent 在第一轮即可感知到未完成任务。
    同时写入 state 供 resume_task 工具读取 flow_id 列表。
    """
    user_id = context.session.state.get("user:id")
    registry = TaskRegistry(base_dir=SESSIONS_DIR)
    active = registry.list_active(user_id, ttl_hours=72)
    
    if not active:
        return CallbackResult()
    
    # 支持多个未完成任务：生成列表供用户选择
    if len(active) == 1:
        task = active[0]
        hint = (
            f"[系统提示] 检测到用户有未完成的【{task['skill_name']}】任务，"
            f"当前在【{task['current_stage']}】阶段（flow_id={task['flow_id']}）。"
            f"请主动询问用户是否继续该任务。"
        )
    else:
        items = "\n".join(
            f"  - {t['skill_name']}（{t['current_stage']} 阶段，flow_id={t['flow_id']}）"
            for t in active
        )
        hint = f"[系统提示] 检测到用户有 {len(active)} 个未完成任务：\n{items}\n请询问用户希望继续哪个。"
    
    return CallbackResult(
        # extra_system_instructions 由框架渲染到 system prompt，Agent 可见
        extra_system_instructions=hint,
        # 同时写入 state，方便 resume_task 工具直接读取可用 flow_id
        context_updates={"_pending_flow_ids": [t["flow_id"] for t in active]},
    )
```

**Step 2: resume_task 工具**

```python
class ResumeTaskTool(AgentTool):
    """恢复未完成的流程任务"""
    name = "resume_task"
    description = "恢复用户之前未完成的业务流程，将之前的进度加载到当前会话"
    
    parameters = [
        ToolParameter(name="flow_id", type="string", required=True,
                      description="要恢复的流程 ID"),
    ]
    
    async def execute(self, tool_call, context=None):
        flow_id = tool_call.arguments.get("flow_id")
        user_id = (context or {}).get("user:id")
        
        registry = TaskRegistry(base_dir=SESSIONS_DIR)
        task = registry.get(user_id, flow_id)
        if not task:
            return AgentToolResult(
                result_type=ToolResultType.ERROR,
                content=f"未找到流程: {flow_id}",
            )
        
        # 将 snapshot 格式转换回 _flow_context 格式并恢复
        old_flow_ctx = self._restore_flow_context(task)
        
        return AgentToolResult(
            result_type=ToolResultType.JSON,
            content={
                "status": "restored",
                "flow_id": flow_id,
                "current_stage": task["current_stage"],
                "message": f"已恢复【{task['skill_name']}】流程，当前在【{task['current_stage']}】阶段",
            },
            metadata={
                # 使用点路径写入，框架深度合并不覆盖其他 state 字段
                "state_delta": {"_flow_context": old_flow_ctx},
            },
        )

    def _restore_flow_context(self, task: dict) -> dict:
        """将 active_tasks.json 的 snapshot 格式转换回 _flow_context 的运行时格式。
        
        snapshot 格式（get_restorable_state 产出）：
            {
              "flow_id": "...",
              "stages": {
                "identity_verify": {"status": "completed", "data": {...}},
                ...
              }
            }
        
        _flow_context 运行时格式（evaluator 读取的格式）：
            {
              "flow_id": "...",
              "skill_name": "withdrawal_flow",
              "stage_identity_verify": {...},   # 直接展平，key = stage_{id}
              ...
            }
        """
        snapshot = task.get("flow_context_snapshot", {})
        flow_ctx: dict = {
            "flow_id": task["flow_id"],
            "skill_name": task["skill_name"],
        }
        for stage_id, stage_info in snapshot.get("stages", {}).items():
            if stage_info.get("status") == "completed" and stage_info.get("data"):
                flow_ctx[f"stage_{stage_id}"] = stage_info["data"]
        return flow_ctx
```

**Step 3: 继续执行**

恢复后 Agent 自动调用 `flow_evaluator`，读取已恢复的 `_flow_context`，Pydantic 校验前序阶段数据完整后，返回当前阶段并继续执行。

---

## 4. 整体架构图

```
┌─────────────────────────────────────────────────────────┐
│ SKILL.md (withdraw_money)                               │
│  frontmatter:                                           │
│    required_tools: [flow_evaluator, identity_service,   │
│                     fund_service, resume_task]          │
│  正文: 流程概述和通用规则（无需显式引用 reference）       │
└──────────────┬──────────────────────────────────────────┘
               │
┌──────────────▼──────────────────────────────────────────┐
│ AgentRunner（最小改动：+Dynamic注入 / +点路径合并）                  │
│                                                         │
│  ReAct Loop:                                            │
│   ┌─────────────────────────────────────────────┐      │
│   │ 1. Agent 调用 flow_evaluator                 │      │
│   │    → 返回: 当前阶段 + 已完成步骤 + 下一步指引│      │
│   │    → state_delta 更新 _flow_stage            │      │
│   │                                              │      │
│   │ 2. 框架自动注入当前阶段的 reference 内容     │      │
│   │    → 下一轮 system prompt 包含阶段 SOP       │      │
│   │                                              │      │
│   │ 3. Agent 按 SOP 调用业务工具                 │      │
│   │    → 结果通过 state_delta 写入 _flow_context │      │
│   │                                              │      │
│   │ 4. Agent 再次调用 flow_evaluator             │      │
│   │    → 确认阶段完成（Pydantic 校验通过）       │      │
│   │    → _flow_stage 更新为下一阶段              │      │
│   │    → 下一轮自动切换 reference                │      │
│   └─────────────────────────────────────────────┘      │
│                                                         │
│  Hooks (不改动接口):                                     │
│   before_agent → 注入未完成任务提示                      │
│   after_agent  → 持久化 _flow_context                   │
└──────────────┬──────────────────────────────────────────┘
               │
┌──────────────▼──────────────────────────────────────────┐
│ 持久化层                                                │
│  storage/{user_id}/active_tasks.json                    │
│   → flow_id, skill_name, current_stage                  │
│   → flow_context_snapshot (FlowEvaluator 产出)          │
│   → resume_ttl_hours, updated_at                        │
└─────────────────────────────────────────────────────────┘
```

---

## 5. 执行流程详解

### 5.1 新建流程

```
1. 用户说"我要取钱"
2. SkillMatcher 匹配到 withdraw_money SKILL
3. Agent 调用 flow_evaluator
   → 检测 _flow_context 为空
   → 初始化新 flow: {flow_id: uuid, stage: identity_verify}
   → state_delta 设置 _flow_stage = "identity_verify"
   → 返回: "当前阶段: 身份核验，请根据参考文档完成操作"
4. 下一轮 system prompt 自动包含 references/identity_verify.md 内容
5. Agent 按 SOP 调用 customer_info, policy_query
   → 结果通过 state_delta 写入 _flow_context.stage_identity_verify
6. Agent 调用 flow_evaluator
   → Pydantic 校验 IdentityVerifyOutput ✓
   → state_delta 更新 _flow_stage = "options_query"
   → 返回: "身份核验完成，进入方案查询阶段"
7. 下一轮 system prompt 自动切换为 references/options_query.md
8. 重复 5-7 直到 plan_confirm 阶段
9. flow_evaluator 返回 user_required_fields（confirmed、selected_option、amount）
   → Agent 调用 render_a2ui 展示方案，等待用户确认
   → 用户确认后 commit_flow_stage → 进入 execute 阶段
10. after_agent hook 持久化 _flow_context
```

### 5.2 跨会话恢复

```
1. 用户第二天开启新对话
2. before_agent hook 检测 active_tasks.json
   → 发现未完成的 withdrawal_flow，阶段 plan_confirm
   → 注入系统提示
3. 用户说"继续昨天的取款"
4. Agent 调用 resume_task(flow_id)
   → 从 active_tasks.json 恢复 _flow_context
   → 通过 state_delta 注入当前 session
5. Agent 调用 flow_evaluator
   → 读取恢复的 _flow_context
   → 校验前两阶段数据完整（Pydantic 通过）
   → 返回: "当前阶段: 方案确认，等待用户确认"
6. 用户确认 → 进入 execute 阶段
```

---

## 6. 与传统 DAG 编排方案的对比

| 维度 | 传统 DAG 编排（FlowEngine） | Agentic Native（本方案） |
|------|---------------------------|-------------------------|
| 框架改动 | 新增 FlowEngine/Store/Router 三模块 | 零改动，仅增加工具和 Hook |
| 步骤执行 | 框架强制顺序执行 | FlowEvaluator 确定性评估 + Agent 遵循 |
| 工具隔离 | ephemeral session + tools 白名单 | reference SOP 中指定（知识引导） |
| 数据校验 | 无（condition 表达式仅做路由） | Pydantic schema 严格校验 |
| 灵活性 | 固定 DAG，变更需修改 frontmatter | Agent 可灵活应对异常情况 |
| 可维护性 | 框架代码维护成本高 | 每个业务独立 Evaluator，互不影响 |
| Token 效率 | 每步独立 session | reference 按需加载 + _flow_context 精简 |

---

## 7. 新增文件清单

```
src/ark_agentic/
├── core/
│   ├── flow/
│   │   ├── base_evaluator.py          # BaseFlowEvaluator + StageDefinition + FlowEvaluatorRegistry
│   │   ├── task_registry.py           # TaskRegistry（active_tasks.json 管理）
│   │   └── callbacks.py               # persist_flow_context, inject_flow_hint（框架核心）
│   └── tools/
│       └── resume_task.py             # ResumeTaskTool（恢复中断流程）
│
└── agents/insurance/
    ├── tools/
    │   └── flow_evaluator.py          # WithdrawalFlowEvaluator（继承 BaseFlowEvaluator）
    └── skills/withdraw_money/
        ├── SKILL.md                   # 无需显式引用 reference
        └── references/               # 阶段 SOP 文档（框架自动注入）
            ├── identity_verify.md
            ├── options_query.md
            ├── plan_confirm.md
            └── execute.md
```

---

## 8. 实施计划

### Phase 1: 基础设施（2 天）

- [ ] 实现 `BaseFlowEvaluator` 抽象基类 + `StageDefinition` + `FlowEvaluatorRegistry`（`core/flow/base_evaluator.py`）
- [ ] 实现 `TaskRegistry`（active_tasks.json 读写 + TTL 清理）
- [ ] 实现 `persist_flow_context` / `inject_flow_hint` 框架回调（`core/flow/callbacks.py`）
- [ ] 修改 `SkillLoader` 支持 `references/` 自动扫描（FULL 模式）
- [ ] 修改 `_build_system_prompt()` 支持 `_flow_stage` + `FlowEvaluatorRegistry` 驱动的 Dynamic 注入
- [ ] 修改 `AgentRunner._apply_state_delta()` 支持点路径（dot-path）深度合并
- [ ] 在 `SystemPromptBuilder` 中支持 `extra_system_instructions` 渲染（供 `inject_flow_hint` 使用）
- [ ] 实现 `ResumeTaskTool`（含 `_restore_flow_context` snapshot→运行时格式转换）

### Phase 2: 业务实现（2 天）

- [ ] 实现 `WithdrawalFlowEvaluator`（继承 `BaseFlowEvaluator`，定义 4 阶段 + Pydantic schema）
- [ ] 编写 4 个阶段的 reference SOP 文档（`references/*.md`）
- [ ] 编写 `withdraw_money` SKILL.md（无需显式引用 reference，框架自动注入）
- [ ] 在 Agent 注册时挂载 `core/flow/callbacks.py` 中的 `after_agent` / `before_agent` Hook

### Phase 3: 集成测试（1 天）

- [ ] 端到端测试：新建流程 → 4 阶段执行 → 完成
- [ ] 中断恢复测试：挂起 → 新 session → resume → 继续
- [ ] Pydantic 校验测试：阶段数据不完整 → evaluator 返回 incomplete
- [ ] TTL 过期测试

---

## 9. 风险与缓解

| 风险 | 严重度 | 缓解措施 |
|------|--------|---------|
| LLM 不调用 flow_evaluator 直接执行业务工具 | 中 | SKILL 正文强调"必须先调用 flow_evaluator" |
| _flow_context 被其他工具意外覆盖 | 低 | 命名空间隔离（`_` 前缀约定） |
| reference 内容过长导致 token 溢出 | 低 | 每个 reference 控制在 2000 字以内 |
| 业务工具 state_delta 写入格式不符预期 | 中 | FlowEvaluator 校验时明确报错并指引 |
| active_tasks.json 并发写入 | 低 | 复用现有 FileLock 机制 |
