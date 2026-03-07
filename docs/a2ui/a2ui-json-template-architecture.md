# A2UI 基于 JSON 模板的渲染架构

## 问题

当前 `src/ark_agentic/agents/insurance/a2ui/template_renderer.py` 中 `render_withdraw_summary` 用 Python 手写整棵组件树（约 200 行）。每增加一种卡片都要在这里加一个方法并重复类似逻辑，难以扩展。

`a2ui-withdraw-ui-schema.json` 只描述 **data** 结构（扁平字段 + `plan_action_args`）；`a2ui-withdraw-ui-smaple.json` 则是完整的 A2UI 协议负载（components 树 + data 扁平键值）。样本里组件树是**静态**的，明细行用固定 path：`zero_cost_item_1_label`、`zero_cost_item_2_label` 等。

## 目标

- **新增卡片**：只增加「模板 JSON + 可选 schema」和「工具内的数据提取 + 扁平化」，不在 `template_renderer.py` 里写新布局代码。
- **渲染器**：通用逻辑「按 card_type 加载 template.json → 注入 surfaceId → 合并 data → 返回 A2UI 负载」。

## 方案：模板 JSON + 扁平 data + 工具侧列表展开

### 1. 模板文件约定

每个卡片类型一个目录，目录名即 `card_type`：

```
agents/insurance/a2ui/templates/
  withdraw_summary/
    template.json   # 完整 A2UI 组件树 + 空 data（或占位 data）
    schema.json     # 可选，用于校验 data 形状
```

- **template.json** 格式与 a2ui-standard 一致：
  - 包含 `event`, `version`, `rootComponentId`, `style`, `hideVoteRecorder`, `components`, `data`。
  - `data` 可为空 `{}` 或占位；渲染时用传入的 `data` 覆盖。
  - `surfaceId` 不在模板里写死，由渲染器按 `{card_type}-{session_id[:8]}-{uuid}` 生成。
  - 组件树里所有绑定都用 **path** 指向 data 的键（如 `header_title`, `zero_cost_item_1_label`），与 schema 的扁平结构一致。

- **schema.json**：可复用 `docs/a2ui/a2ui-withdraw-ui-schema.json`，仅用于可选校验。

### 2. 数据形态：一律扁平

- 协议要求前端拿到的 `data` 是键值对，组件通过 `path` 取标量。因此**进入渲染器的 data 必须扁平**。
- 对于「列表型」业务数据（如 `zero_cost_items: [{label, value}, ...]`）：
  - **在工具内**先展开为扁平字段：`zero_cost_item_1_label`, `zero_cost_item_1_value`, ..., `zero_cost_item_N_*`（与 schema 一致），最多 N 条（如 N=5），不足填空串。
  - 模板中固定写 `cz-item-1`..`cz-item-N`，绑定 `zero_cost_item_1_label` 等；渲染器不理解「列表」。

渲染器**只做**：读 JSON、填 surfaceId、合并 data，不做列表展开或动态生成组件。

### 3. 渲染器 API（通用）

```python
def render(card_type: str, data: dict[str, Any], session_id: str = "") -> dict[str, Any]:
    """
    加载 templates/{card_type}/template.json，注入 surfaceId，用 data 覆盖模板中的 data，返回完整 A2UI 负载。
    data 必须为扁平（仅标量 + 可选 plan_action_args 等 object）。
    """
```

- 实现要点：
  - 从 `templates/{card_type}/template.json` 读入整份 A2UI 结构。
  - 生成 `surface_id = f"{card_type}-{session_id[:8]}-{uuid4().hex[:6]}"`。
  - `payload["surfaceId"] = surface_id`，`payload["data"] = {**template.get("data", {}), **data}`（传入 data 优先）。
  - 可选：若存在 `templates/{card_type}/schema.json`，用 jsonschema 校验 `data`。
- 不再保留 `render_withdraw_summary` 等卡片专用方法；`WithdrawCardTool` 改为调用 `InsuranceCardRenderer.render("withdraw_summary", flat_data, session_id)`。

### 4. 工具侧职责（以 withdraw 为例）

- **WithdrawCardTool**：
  1. 从 context 取 `_rule_engine_result`。
  2. 确定性计算得到 `zero_cost_items`、`loan_items` 等列表。
  3. **扁平化**：将 `zero_cost_items` 展开为 `zero_cost_item_1_label`, `zero_cost_item_1_value`, ..., `zero_cost_item_5_*`（不足补 `""`）；`loan_items` 同理。并写入 `header_*`, `zero_cost_title`, `advice_*`, `plan_button_text`, `plan_action_args` 等。
  4. （可选）用 schema 校验扁平后的 data。
  5. 调用 `InsuranceCardRenderer.render("withdraw_summary", flat_data, session_id)`，返回 `AgentToolResult.a2ui_result(...)`。

列表 → 扁平的转换放在各自工具内；渲染器保持无状态、只认扁平 data。

### 5. 新增卡片流程（后续）

1. 在 `templates/` 下新建目录，如 `templates/xxx_summary/`。
2. 新增 `template.json`：可从 withdraw 样本复制后改 id/绑定 path；`data` 置为 `{}`。
3. 可选：新增或复用 `schema.json`。
4. 新增或扩展现有 Tool：取数据 → 计算 → **扁平化**（含列表展开）→ 可选校验 → `InsuranceCardRenderer.render("xxx_summary", flat_data, session_id)`。
5. **无需**改 `template_renderer.py`。

### 6. 与现有实现的衔接

- 当前 `render_withdraw_summary` 动态生成 N/M 条明细；样本和 schema 是固定 2 条。迁移后采用「固定最多 N 条 + 不足填空」的扁平 data，与 schema 一致。
- 若需「超出 N 条时显示及 X 项」，可在工具扁平化时写入 `zero_cost_overflow_text` 等字段，模板中加一行 Text 绑定即可。

### 7. 文件与依赖

| 项 | 说明 |
|----|------|
| 模板路径 | `src/ark_agentic/agents/insurance/a2ui/templates/withdraw_summary/template.json` |
| 模板内容 | 从 a2ui-withdraw-ui-smaple.json 拷贝，data 清空；surfaceId 由渲染器填充 |
| schema | 可拷贝 a2ui-withdraw-ui-schema.json 到 templates/withdraw_summary/schema.json |
| 渲染器 | 删除 render_withdraw_summary；新增通用 render(card_type, data, session_id) |
| jsonschema | 若做 schema 校验需加依赖；否则可省略 |

### 8. 小结

- **模板驱动**：每种卡片一个 template.json，组件树完全由 JSON 描述。
- **数据扁平**：data 仅含标量（及 plan_action_args 等）；列表在**工具内**展开为 item_1, item_2, ...。
- **渲染器单一职责**：按 card_type 加载模板、生成 surfaceId、合并 data、返回 A2UI 负载。
- **扩展方式**：新卡片 = 新目录（template + 可选 schema）+ 新/扩工具（提取 + 扁平化）+ 调用 `render(card_type, flat_data, session_id)`。
