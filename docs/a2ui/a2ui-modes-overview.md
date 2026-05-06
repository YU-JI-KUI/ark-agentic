# A2UI 双模式架构 — preset / dynamic

## 0. 文档用途

本文档是 A2UI 渲染系统的单一事实来源，描述 v4 架构（preset/dynamic 双模式）。

## 1. 两种交付模式

| 模式 | Wire 形态 | 典型 Agent | LLM 工具 |
|------|-----------|------------|----------|
| **preset** | `{ template_type, data }` | 证券 | `display_card` |
| **dynamic** | 完整 A2UI 组件树 | 保险 | `render_a2ui` |

- **preset**：后端传 `template_type` + `data`，前端按预制组件渲染。
- **dynamic**：后端生成完整 A2UI 组件树（`components` + `data`），前端通用渲染。

模式由 Agent factory 在工具注册时固定（证券注册 `display_card`，保险注册 `render_a2ui`），无运行时切换配置。

## 2. dynamic 模式

### 2.1 核心定义

Dynamic 块注册表和 JSON 模板（`template.json`）是同一个概念的两种展开方式：

- **动态块**：LLM 从注册块中选择组合 + 填 data → `BlockComposer` 展开为完整 A2UI 树。
- **template.json**：等价于一个确定性大块的 JSON 快照——跳过 LLM 编排、只填 data。

它们共享同一管线：`块/模板 → 完整 A2UI 树 → 统一校验（guard.py）→ 输出`。

### 2.2 render_a2ui 工具

单一工具 `render_a2ui`，4 个参数：

| 参数 | 说明 | 互斥 |
|------|------|------|
| `blocks` | 块描述数组；`items` 为 `oneOf` per type 的严格 schema（`type` 用 `const`，`data` 按 type 独立 schema，内联 transform specs） | 与 card_type 二选一 |
| `card_type` | 预定义卡片类型（如 withdraw_summary） | 与 blocks 二选一 |
| `card_args` | card_type 的可选 JSON 参数 | 仅 card_type 路径 |
| `surface_id` | 可选，有则更新已有画布，无则创建新画布 | 通用 |

- `blocks` → BlockComposer 管线；tool schema 为 `{type: array, items: {oneOf: [...]}}`，LLM 直接输出 JSON 数组，无需字符串包裹
- 可用 type 由 agent factory 决定：`agent_blocks ∪ {"Card"} ∪ agent_components`；未声明 `block_data_schemas` 的 type 退化为 `{type:object, additionalProperties:true}`
- `Card.children` 由框架层自动注入；业务只声明自己的 data schema（DIP 分层）
- `card_type` → render_from_template + 提取器
- `surface_id` 有则 `surfaceUpdate`，无则 `beginRendering`

### 2.3 Transforms 内联

Transform specs 直接写在 block data 中，不再需要单独的 `transforms` 参数和 `$field` 间接引用：

```python
# block data 值可以是：
# - 字符串/数值/数组 → 直接作为 literal
# - Transform spec 对象 → 运行时求值
blocks=[{"type": "SummaryHeader", "data": {
    "title": "可领取总金额",
    "value": {"get": "total_available_incl_loan", "format": "currency"},
    "subtitle": {"concat": ["不含贷款：", {"get": "total_excl_loan", "format": "currency"}]}
}}]
```

### 2.4 块类型速查

| 类型 | 数据槽 | 说明 |
|------|--------|------|
| `SummaryHeader` | `title, value, subtitle?, note?` | 顶部汇总 |
| `SectionCard` | `title, tag?, total, items` | 分组卡片 |
| `InfoCard` | `title, body` | 信息卡片 |
| `AdviceCard` | `icon?, title, texts[]` | 建议卡片 |
| `KeyValueList` | `items` 或 `rowCount + rowPrefix` | KV 列表 |
| `ItemList` | `items, titleField, tagField?, valueField, subtitleField?` | 项目列表 |
| `ActionButton` | `text, action, variant?` | 操作按钮 |
| `ButtonGroup` | `buttons[]` | 多按钮行 |
| `Divider` | _(无)_ | 分割线 |
| `TagRow` | `tags[]` | 标签行 |
| `ImageBanner` | `url, fit?` | 图片横幅 |
| `StatusRow` | `label, value, status?` | 状态行 |
| `FundsSummary` | _(确定性大块)_ | 取款卡片快照 |

### 2.5 统一校验层（guard.py）

```
blocks / template.json → 展开为完整 A2UI payload
     ↓
┌─────────────────────────────┐
│ core/a2ui/guard.py          │
│  L1: validate_event_payload │
│  L2: validate_payload       │
│  L3: validate_data_coverage │
│  L4: strict/warn 策略       │
└─────────────────────────────┘
     ↓
AgentToolResult.a2ui_result
```

## 3. preset 模式

### 3.1 流程

数据工具写入上下文 → LLM 调用 `display_card(source_tool)` → 字段提取 → `PresetRegistry` → `AgentToolResult.a2ui_result`。

### 3.2 PresetRegistry

`core/a2ui/preset_registry.py` 提供注册表，各 Agent 在 factory 中注册 `template_type` → builder。

## 4. 模式归属

模式在 Agent factory 中通过工具注册硬绑定，无独立配置字段：

- 保险 Agent → 注册 `render_a2ui` 工具 → dynamic 管线
- 证券 Agent → 注册 `display_card` 工具 → preset 管线

## 5. 框架目录结构

```
src/ark_agentic/core/a2ui/
  renderer.py          # render_from_template
  blocks.py            # 块注册表 + builder
  composer.py          # BlockComposer + inline transform 解析
  transforms.py        # Transform DSL
  validator.py         # 组件/binding 校验
  contract_models.py   # 事件级校验
  guard.py             # 统一校验入口
  preset_registry.py   # preset 注册表

src/ark_agentic/core/tools/
  render_a2ui.py       # 合并后的单工具
```

## 6. 相关文档与代码索引

| 资源 | 路径 |
|------|------|
| A2UI 协议与组件 | `docs/a2ui/a2ui-standard.md` |
| 取款 data schema / 样例 | `docs/a2ui/a2ui-withdraw-ui-schema.json`、`a2ui-withdraw-ui-smaple.json` |
| 模板渲染 | `src/ark_agentic/core/a2ui/renderer.py` |
| 渲染工具 | `src/ark_agentic/core/tools/render_a2ui.py` |
| 保险模板 + 提取器 | `src/ark_agentic/agents/insurance/a2ui/` |
| 证券展示 | `src/ark_agentic/agents/securities/tools/display_card.py` |
