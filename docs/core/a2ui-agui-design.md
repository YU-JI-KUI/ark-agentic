# A2UI & AG-UI 设计要点

## 1. AG-UI：流式事件协议

### 定位
Agent → 前端的**实时通信总线**，基于 SSE 传输。所有 Agent 输出（文本、工具调用、UI 组件）都统一封装为 AG-UI 事件。

### 事件模型（17 种）

| 分组 | 事件类型 |
|------|----------|
| 生命周期 | `run_started` / `run_finished` / `run_error` |
| 步骤 | `step_started` / `step_finished` |
| 文本流 | `text_message_start` / `text_message_content` / `text_message_end` |
| 工具调用 | `tool_call_start` / `tool_call_args` / `tool_call_end` / `tool_call_result` |
| 状态同步 | `state_snapshot` / `state_delta` |
| 消息快照 | `messages_snapshot` |
| 思考流 | `thinking_message_start` / `thinking_message_content` / `thinking_message_end` |
| 自定义 | `custom` / `raw` |

A2UI 组件通过 `text_message_content`（`content_kind=a2ui`）或 `custom` 事件透传。

### 多协议适配（OutputFormatter）

底层一套事件，输出层做格式区分：

| 协议 | 说明 |
|------|------|
| `agui` | 裸 AG-UI 原生事件 |
| `enterprise` | AGUIEnvelope 包装（企业信封） |
| `internal` | 旧版 `response.*` 格式（向后兼容） |
| `alone` | 旧版 ALONE 协议（`sa_*` 事件） |

### 设计关键点
- **单一内部模型**：`AgentStreamEvent` 是唯一内部数据结构，序号 `seq` 保序
- **ReAct 轮次追踪**：`turn` 字段区分中间推理轮与最终答案轮
- **Runner 信号 → AG-UI 展开**：5 个 Runner 回调信号由 `StreamEventBus` 展开为完整 AG-UI 序列

---

## 2. A2UI：富交互前端组件协议

### 定位
后端驱动的**声明式 UI 渲染协议**——后端描述"渲染什么"，前端通用渲染引擎负责"如何渲染"。样式完全由后端的设计 Token 决定，LLM 无法控制颜色/字体/间距。

### 两种交付模式

| 模式 | 传输形态 | 典型 Agent | 触发工具 |
|------|----------|------------|----------|
| **preset** | `{ template_type, data }` | 证券 Agent | `display_card` |
| **dynamic** | 完整组件树（`components` + `data`） | 保险 Agent | `render_a2ui` |

- **preset**：LLM 只选 `template_type`，前端按预制组件渲染，数据结构固定。
- **dynamic**：LLM 从块注册表中选择组合 + 填数据，`BlockComposer` 展开为完整 A2UI 树。

### Wire 格式核心字段

```json
{
  "event": "beginRendering | surfaceUpdate | dataModelUpdate | deleteSurface",
  "surfaceId": "画布唯一 ID",
  "rootComponentId": "根组件 ID",
  "components": [...],   // 组件扁平列表（与 catalogId 互斥）
  "data": { "key": "value" }  // 绑定数据
}
```

组件属性绑定格式：`{ "path": "dataKey" }` 引用 `data`，`{ "literalString": "..." }` 为硬编码值。

### Dynamic 模式管线

```
LLM 选块 + 填 data
    ↓
BlockComposer（内联 Transform 求值）
    ↓
完整 A2UI 组件树
    ↓
guard.py 三层校验（事件契约 / 组件 binding / 数据覆盖）
    ↓
AgentToolResult.a2ui_result
```

### 内置块类型（Block Registry）

| 类型 | 用途 |
|------|------|
| `SummaryHeader` | 顶部英雄卡（标题 + 高亮值） |
| `SectionCard` | 分组标题 + KV 列表 |
| `InfoCard` | 信息展示卡 |
| `AdviceCard` | 建议/提示卡 |
| `KeyValueList` | KV 行列表 |
| `ItemList` | 项目列表（支持 List 组件动态渲染） |
| `ActionButton` | 操作按钮 |
| `ButtonGroup` | 多按钮行 |
| `TagRow` | 标签行 |
| `ImageBanner` | 图片横幅 |
| `StatusRow` | 状态行 |

### Transform DSL

Block data 的值可以是内联 transform spec，在 compose 阶段确定性求值（无 LLM 参与）：

| 操作符 | 用途 |
|--------|------|
| `get` | 路径取值，支持点分隔 + 数组下标 |
| `sum` | 数组字段求和 |
| `count` | 数组计数（支持 where 过滤） |
| `concat` | 字符串拼接 |
| `select` | 数组 filter + map（构造子列表） |
| `switch` | 枚举值映射 |
| `literal` | 字面量 |

### 设计关键点
- **样式封闭**：设计 Token（颜色、间距、字号）统一定义在 `blocks.py`，LLM 只控制数据，不控制样式
- **校验分层**：L1 事件契约 → L2 组件/binding 结构 → L3 数据覆盖率，三层独立可配置
- **双路径等价**：`blocks`（LLM 动态编排）和 `card_type`（预定义模板）共享同一 guard.py 校验管线
- **`surfaceId` 复用**：相同 `surfaceId` 触发 `surfaceUpdate`（更新画布），新 ID 触发 `beginRendering`（创建画布）

---

## 3. 两者关系

```
AG-UI 流式协议
  └── text_message_content (content_kind=a2ui)
  └── custom 事件
        └── A2UI payload（preset 或 dynamic）
```

AG-UI 是**传输容器**，A2UI 是**UI 渲染载荷**。Agent 工具调用返回 `AgentToolResult.a2ui_result`，由 `StreamEventBus` 包装为 AG-UI 事件下发给前端。
