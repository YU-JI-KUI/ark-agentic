# Flow DSL 配置化改造方案

## 1. 背景与目标

### 现状

当前 flow 定义（如 `WithdrawalFlowEvaluator`）采用 Python 硬编码方式实现，每个业务流程需要：

- 编写 Pydantic Model 类定义各阶段 output_schema
- 继承 `BaseFlowEvaluator`，硬编码 `stages` 属性返回 `StageDefinition` 列表
- 在 `FieldSource` 中嵌入 `lambda` 实现数据提取（如 `transform=lambda r: [p["policy_id"] for p in r.get("policyAssertList", [])]`）
- 手动调用 `FlowEvaluatorRegistry.register()` 完成注册

**问题**：
1. 新增流程必须写 Python 代码，门槛高且容易出错
2. 流程定义散落在 Python 文件中，无法可视化编辑
3. `lambda` 无法序列化，阻碍 DSL 化和配置化
4. 业务定义与框架代码耦合在同一文件中

### 目标

将 flow 定义从 Python 硬编码改为 **YAML 声明式配置 + 内置 transform 算子**：

1. **新增 flow 只需一个 YAML 文件**，无需编写任何 Python
2. **transform 用预置算子替代 lambda**，覆盖当前全部使用场景
3. **框架层新增 FlowLoader**，从 YAML 动态组装 `BaseFlowEvaluator` 实例
4. **向后兼容**，已有的 Python 硬编码 flow 可与 YAML flow 共存

---

## 2. 设计方案

### 2.1 YAML Flow 定义规范

每个 flow 对应一个 YAML 文件，放在 `skills/<skill_name>/flow.yaml` 中：

```yaml
# skills/withdraw_money_flow/flow.yaml
skill_name: withdraw_money_flow

stages:
  - id: identity_verify
    name: 身份核验
    description: 验证客户身份和保单信息
    required: true
    checkpoint: false
    reference_file: identity_verify.md
    tools:
      - customer_info
      - policy_query
    output_schema:
      user_id: string
      id_card_verified: boolean
      policy_ids:
        type: array
        items: string
    field_sources:
      user_id:
        source: tool
        state_key: _customer_info_result
        path: user_id
      id_card_verified:
        source: tool
        state_key: _customer_info_result
        path: identity.verified
      policy_ids:
        source: tool
        state_key: _policy_query_result
        transform:
          operator: pluck
          path: policyAssertList
          field: policy_id

  - id: options_query
    name: 方案查询
    description: 查询可取款选项和金额
    required: true
    checkpoint: false
    reference_file: options_query.md
    tools:
      - rule_engine
    output_schema:
      available_options:
        type: array
        items: object
      total_cash_value: number
      max_withdrawal: number
    field_sources:
      available_options:
        source: tool
        state_key: _rule_engine_result
        path: options
      total_cash_value:
        source: tool
        state_key: _rule_engine_result
        path: total_available_excl_loan
      max_withdrawal:
        source: tool
        state_key: _rule_engine_result
        path: total_available_incl_loan

  - id: plan_confirm
    name: 方案确认
    description: 向用户展示方案并等待确认
    required: true
    checkpoint: true
    reference_file: plan_confirm.md
    tools:
      - render_a2ui
    delta_state_keys:
      - _plan_allocations
    output_schema:
      confirmed: boolean
      selected_option: object
      amount: number
    field_sources:
      confirmed:
        source: user
        description: 用户是否确认方案（true/false）
      selected_option:
        source: user
        description: 用户选择的方案，含 channels（渠道列表）和 target（目标金额）
      amount:
        source: user
        description: 最终确认的取款金额（元，浮点数）

  - id: execute
    name: 执行取款
    description: 提交取款操作
    required: true
    checkpoint: false
    reference_file: execute.md
    tools:
      - submit_withdrawal
    output_schema:
      submitted: boolean
      channels:
        type: array
        items: string
    field_sources:
      submitted:
        source: tool
        state_key: _submitted_channels
        transform:
          operator: truthy
      channels:
        source: tool
        state_key: _submitted_channels
```

#### YAML 字段说明

| 顶层字段 | 类型 | 必填 | 说明 |
|----------|------|------|------|
| `skill_name` | string | 是 | 关联的 SKILL 目录名，同时作为工具 name 前缀 |

| stage 字段 | 类型 | 必填 | 默认值 | 说明 |
|------------|------|------|--------|------|
| `id` | string | 是 | - | 阶段唯一标识 |
| `name` | string | 是 | - | 阶段中文名 |
| `description` | string | 是 | - | 阶段描述 |
| `required` | boolean | 否 | true | 是否必须阶段 |
| `checkpoint` | boolean | 否 | false | 是否触发持久化写盘 |
| `reference_file` | string | 否 | null | references/ 下的文件名 |
| `tools` | string[] | 否 | [] | 建议使用的工具列表 |
| `output_schema` | object | 否 | null | 阶段完成条件 Schema（简写格式） |
| `field_sources` | object | 否 | {} | 字段来源声明 |
| `delta_state_keys` | string[] | 否 | [] | 额外快照的 state key |

#### output_schema 简写格式

支持两种写法：

**简写**（标量类型）：`field_name: type`，type 为 `string` | `boolean` | `number` | `object`

**完整写法**（数组/嵌套）：
```yaml
policy_ids:
  type: array
  items: string
```

#### field_sources 字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `source` | string | 是 | `"tool"` 或 `"user"` |
| `state_key` | string | source=tool 时必填 | session.state 中的 key |
| `path` | string | 否 | 点路径遍历（如 `identity.verified`） |
| `description` | string | source=user 时建议填写 | 字段说明，注入提示词 |
| `transform` | object | 否 | 内置算子声明（见下节） |

---

### 2.2 Transform 算子规范

算子替代原有的 `lambda`，以声明式 YAML 对象表达：

```yaml
transform:
  operator: <算子名>
  ...参数
```

#### 内置算子清单

| 算子 | 语义 | 参数 | 替代的 lambda |
|------|------|------|--------------|
| `pluck` | 从列表中提取指定字段 | `path`: 列表字段路径, `field`: 要提取的字段名 | `lambda r: [p["policy_id"] for p in r.get("policyAssertList", [])]` |
| `truthy` | 转布尔值 | 无 | `lambda channels: bool(channels)` |
| `identity` | 直接取值（默认行为） | 无 | 无 transform 时的行为 |
| `cast_int` | 转整数 | 无 | `lambda r: int(r)` |
| `cast_float` | 转浮点数 | 无 | `lambda r: float(r)` |
| `first` | 取列表首个元素 | 无 | `lambda r: r[0]` |
| `last` | 取列表末尾元素 | 无 | `lambda r: r[-1]` |
| `default` | 空值兜底 | `value`: 兜底值 | `lambda r: r or {}` |
| `len` | 取长度 | 无 | `lambda r: len(r)` |
| `keys` | 取字典 key 列表 | 无 | `lambda r: list(r.keys())` |
| `lookup` | 按点路径取值 | `path`: 点路径字符串 | 与 `path` 字段等价，但可用于复杂路径 |
| `pipe` | 管道组合多个算子 | `steps`: 算子列表 | 多步转换组合 |

#### 算子使用示例

**pluck** — 从列表提取字段：
```yaml
# 原 lambda: lambda r: [p["policy_id"] for p in r.get("policyAssertList", []) if "policy_id" in p]
transform:
  operator: pluck
  path: policyAssertList   # 可选，先按路径取到列表
  field: policy_id         # 从每个元素中提取的字段
```

**truthy** — 转布尔：
```yaml
# 原 lambda: lambda channels: bool(channels)
transform:
  operator: truthy
```

**pipe** — 管道组合：
```yaml
# 先取列表，再取长度，再转布尔
transform:
  operator: pipe
  steps:
    - operator: lookup
      path: policyAssertList
    - operator: len
    - operator: truthy
```

**default** — 空值兜底：
```yaml
transform:
  operator: default
  value: {}
```

---

### 2.3 FlowLoader 实现

框架层新增 `FlowLoader`，负责从 YAML 文件加载 flow 定义并组装为 `BaseFlowEvaluator` 实例。

#### 核心逻辑

```python
# core/flow/flow_loader.py

class FlowLoader:
    """从 YAML 文件加载 flow 定义，组装为 BaseFlowEvaluator 实例。"""

    @classmethod
    def from_yaml(cls, path: Path) -> BaseFlowEvaluator:
        """从 YAML 文件加载并返回已注册的 evaluator 实例。"""
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        stages = [_build_stage(s) for s in raw["stages"]]
        evaluator = _DynamicFlowEvaluator(raw["skill_name"], stages)
        FlowEvaluatorRegistry.register(evaluator)
        return evaluator

    @classmethod
    def from_skill_dir(cls, skill_dir: Path) -> BaseFlowEvaluator | None:
        """从 SKILL 目录中查找 flow.yaml 并加载。"""
        flow_file = skill_dir / "flow.yaml"
        if flow_file.exists():
            return cls.from_yaml(flow_file)
        return None
```

#### 动态 Pydantic Model 生成

YAML 中的 `output_schema` 需要转换为 Pydantic Model 类，用于数据校验：

```python
def _build_output_schema(schema_def: dict[str, Any] | None, stage_id: str) -> type[BaseModel] | None:
    """从 YAML schema 定义动态创建 Pydantic Model 类。"""
    if not schema_def:
        return None

    type_mapping = {
        "string": (str, ...),
        "boolean": (bool, ...),
        "number": (float, ...),
        "object": (dict, ...),
    }

    fields = {}
    for field_name, field_def in schema_def.items():
        if isinstance(field_def, str):
            # 简写格式：field_name: type
            py_type = type_mapping.get(field_def, (Any, ...))
            fields[field_name] = py_type
        elif isinstance(field_def, dict):
            # 完整格式
            if field_def.get("type") == "array":
                items_type = type_mapping.get(field_def.get("items", "string"), (Any, ...))[0]
                fields[field_name] = (list[items_type], ...)  # type: ignore
            else:
                py_type = type_mapping.get(field_def.get("type", "string"), (Any, ...))
                fields[field_name] = py_type

    # 动态创建 Pydantic Model
    return create_model(f"{stage_id}_output", **fields)
```

#### 动态 Evaluator 子类创建

```python
def _DynamicFlowEvaluator(skill_name: str, stages: list[StageDefinition]) -> BaseFlowEvaluator:
    """通过 type() 动态创建 BaseFlowEvaluator 子类实例。"""

    class _DynamicEvaluator(BaseFlowEvaluator):
        @property
        def skill_name(self) -> str:
            return _skill_name

        @property
        def stages(self) -> list[StageDefinition]:
            return _stages

    _skill_name = skill_name
    _stages = stages
    return _DynamicEvaluator()
```

---

### 2.4 Transform 算子执行器

```python
# core/flow/transform_operator.py

from typing import Any, Callable

class TransformOperator:
    """内置 transform 算子注册表与执行器。"""

    _operators: dict[str, Callable[..., Any]] = {}

    @classmethod
    def register(cls, name: str, fn: Callable[..., Any]) -> None:
        cls._operators[name] = fn

    @classmethod
    def execute(cls, transform_def: dict[str, Any], value: Any) -> Any:
        """执行 transform 定义。"""
        operator_name = transform_def["operator"]
        fn = cls._operators.get(operator_name)
        if fn is None:
            raise ValueError(f"Unknown transform operator: {operator_name}")
        # 将除 operator 外的所有参数传给算子函数
        params = {k: v for k, v in transform_def.items() if k != "operator"}
        return fn(value, **params)

    @classmethod
    def to_callable(cls, transform_def: dict[str, Any]) -> Callable[[Any], Any]:
        """将 transform 定义转为 Callable，供 FieldSource.transform 使用。"""
        def _apply(value: Any) -> Any:
            return cls.execute(transform_def, value)
        return _apply


# ── 内置算子注册 ─────────────────────────────────────────────────────────────

TransformOperator.register("pluck", _pluck)
TransformOperator.register("truthy", _truthy)
TransformOperator.register("identity", lambda v: v)
TransformOperator.register("cast_int", lambda v: int(v))
TransformOperator.register("cast_float", lambda v: float(v))
TransformOperator.register("first", lambda v: v[0])
TransformOperator.register("last", lambda v: v[-1])
TransformOperator.register("default", lambda v, value=None: v if v is not None else value)
TransformOperator.register("len", lambda v: len(v))
TransformOperator.register("keys", lambda v: list(v.keys()))
TransformOperator.register("lookup", _lookup)
TransformOperator.register("pipe", _pipe)


def _pluck(value: Any, *, path: str | None = None, field: str = "") -> Any:
    """从列表中提取指定字段。"""
    if path:
        for part in path.split("."):
            value = value.get(part) if isinstance(value, dict) else None
        if value is None:
            return []
    if not isinstance(value, list):
        return value
    return [item[field] for item in value if isinstance(item, dict) and field in item]


def _truthy(value: Any) -> bool:
    return bool(value)


def _lookup(value: Any, *, path: str = "") -> Any:
    """按点路径取值。"""
    for part in path.split("."):
        value = value.get(part) if isinstance(value, dict) else None
    return value


def _pipe(value: Any, *, steps: list[dict[str, Any]]) -> Any:
    """管道组合多个算子。"""
    result = value
    for step in steps:
        result = TransformOperator.execute(step, result)
    return result
```

---

### 2.5 FlowLoader 与 SkillLoader 集成

在现有 SkillLoader 加载 SKILL 目录时，自动检测 `flow.yaml` 并加载：

```python
# 修改 skill_loader.py 中的加载逻辑（伪代码）

def _load_skill(self, skill_dir: Path) -> SkillEntry | None:
    # ... 现有 SKILL.md 加载逻辑 ...

    # 自动检测并加载 flow.yaml
    from .flow.flow_loader import FlowLoader
    FlowLoader.from_skill_dir(skill_dir)  # 存在则加载并注册，不存在则跳过

    return skill_entry
```

---

### 2.6 create_insurance_tools 适配

`flow_evaluator.py` 中的 Python 硬编码注册代码可移除，改为从 YAML 加载：

**改造前**（当前）：
```python
# tools/__init__.py
from .flow_evaluator import withdrawal_flow_evaluator  # noqa: F401

def create_insurance_tools(...):
    withdrawal_flow_evaluator._task_registry = TaskRegistry(_sessions_dir)
    return [
        ...,
        withdrawal_flow_evaluator,
        ...,
    ]
```

**改造后**：
```python
# tools/__init__.py
from ark_agentic.core.flow.flow_loader import FlowLoader
from ark_agentic.core.flow.base_evaluator import FlowEvaluatorRegistry

def create_insurance_tools(...):
    # FlowLoader 在 SkillLoader 阶段已自动加载 flow.yaml 并注册
    # 此处只需注入 task_registry
    evaluator = FlowEvaluatorRegistry.get("withdraw_money_flow")
    if evaluator:
        evaluator._task_registry = TaskRegistry(_sessions_dir)

    return [
        ...,
        evaluator,  # 可能仍需加入工具列表（取决于 Hook 模式是否需要）
        ...,
    ]
```

---

## 3. 文件变更清单

### 新增文件

| 文件 | 说明 | 预估行数 |
|------|------|---------|
| `core/flow/flow_loader.py` | FlowLoader + 动态 Pydantic Model 生成 + 动态 Evaluator 子类创建 | ~120 行 |
| `core/flow/transform_operator.py` | Transform 算子注册表 + 执行器 + 内置算子实现 | ~100 行 |
| `agents/insurance/skills/withdraw_money_flow/flow.yaml` | 取款流程的 YAML 定义 | ~80 行 |

### 修改文件

| 文件 | 变更内容 | 影响范围 |
|------|----------|---------|
| `core/flow/base_evaluator.py` | `FieldSource.transform` 类型注释增加对算子来源的说明（无运行时变化） | 仅注释 |
| `agents/insurance/tools/flow_evaluator.py` | 删除硬编码的 `WithdrawalFlowEvaluator` 类及 Pydantic Model，保留为空文件或完全删除 | 删除 ~186 行 |
| `agents/insurance/tools/__init__.py` | 移除 `from .flow_evaluator import withdrawal_flow_evaluator`，改为从 `FlowEvaluatorRegistry.get()` 获取 | ~5 行改动 |
| `core/skill_loader.py`（或对应加载入口） | 新增 `FlowLoader.from_skill_dir()` 调用 | ~3 行改动 |

### 删除文件

| 文件 | 说明 |
|------|------|
| `agents/insurance/tools/flow_evaluator.py` | 硬编码定义，被 `flow.yaml` 替代 |

---

## 4. 向后兼容

### 4.1 Python 硬编码 flow 与 YAML flow 共存

`FlowEvaluatorRegistry` 不区分注册来源，Python 硬编码的 `BaseFlowEvaluator` 子类实例和 `FlowLoader.from_yaml()` 创建的动态实例使用相同的注册和查询接口。

共存规则：
- 若 SKILL 目录下同时存在 `flow.yaml` 和 Python 硬编码 evaluator，**Python 硬编码优先**（后注册会覆盖，日志告警）
- 已有 Python 硬编码流程可逐步迁移，无需一次性全部切换

### 4.2 FieldSource.transform 兼容

`FieldSource.transform` 字段类型保持 `Callable | None` 不变。`FlowLoader` 在加载 YAML 时调用 `TransformOperator.to_callable()` 将算子定义转为 Callable 赋给 `transform`，对 `BaseFlowEvaluator._extract_field()` 和 `CollectUserFieldsTool` 完全透明。

---

## 5. 测试计划

### 5.1 单元测试

| 测试项 | 验证内容 |
|--------|---------|
| `TestTransformOperator` | 每个内置算子的正确性（pluck、truthy、pipe 等） |
| `TestFlowLoader` | YAML → StageDefinition 列表的正确解析 |
| `TestBuildOutputSchema` | 简写/完整格式 → Pydantic Model 的正确生成和校验 |
| `TestDynamicEvaluator` | 动态创建的 evaluator 能正确完成 evaluate / auto_commit / get_restorable_state |
| `TestYamlFlowE2E` | 从 YAML 加载 → 注册 → evaluate → auto_commit 全链路 |
| `TestBackwardCompat` | Python 硬编码 evaluator 与 YAML evaluator 共存不冲突 |

### 5.2 集成测试

- 使用 `withdraw_money_flow/flow.yaml` 替换现有 Python 硬编码，运行完整的取款流程
- 验证 pending task 检测、resume、rollback 等跨会话场景正常工作

---

## 6. 实施步骤

### Phase 1：框架层（无业务影响）

1. 新增 `core/flow/transform_operator.py`，实现算子注册表和内置算子
2. 新增 `core/flow/flow_loader.py`，实现 FlowLoader + 动态 Model 生成
3. 编写单元测试，确保算子和加载逻辑正确

### Phase 2：业务层迁移（可逆）

4. 创建 `agents/insurance/skills/withdraw_money_flow/flow.yaml`
5. 验证 YAML flow 与 Python 硬编码 flow 的行为一致性
6. 切换 `__init__.py` 中的注册来源
7. 保留 `flow_evaluator.py` 一段时间后删除

### Phase 3：SkillLoader 集成

8. 修改 SkillLoader，自动检测 `flow.yaml` 并调用 `FlowLoader.from_skill_dir()`
9. 验证 Skill 加载 + flow 注册的自动化流程

---

## 7. 风险与缓解

| 风险 | 缓解措施 |
|------|---------|
| 动态 Pydantic Model 的字段类型推断不如硬编码精确 | 简写格式覆盖 90% 场景；极端情况可回退到 Python 硬编码 |
| 内置算子不够用时需扩展 | 算子可渐进注册（`TransformOperator.register()`）；极端场景降级到 Python 硬编码 |
| YAML 拼写错误导致运行时才暴露 | FlowLoader 加载时做 schema 校验（可用 pydantic 校验 YAML 结构） |
| 动态创建的类调试体验差 | 在 `__repr__` / `__name__` 中注入 skill_name 和 stage 信息 |
