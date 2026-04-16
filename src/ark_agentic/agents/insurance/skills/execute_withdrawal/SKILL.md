---
name: 取款执行
description: 仅当对话中已展示过取款方案卡片（render_a2ui WithdrawPlanCard）且用户明确选择了某个渠道要办理时，才使用本技能调用 submit_withdrawal 提交。如果尚未展示方案卡片，本技能不适用，应使用「保险取款」技能。
version: "9.0.0"
invocation_policy: auto
group: insurance
tags:
  - withdrawal
  - execute
required_tools:
  - submit_withdrawal
---

# 取款执行技能

调用 `submit_withdrawal` 唤起办理流程。工具自动从方案数据获取保单和金额，**LLM 只需传 `operation_type`**。工具自动生成用户文案和剩余渠道提醒。

## 何时使用本技能

同时满足：
1. 对话中已有 PlanCard（digest 可见）
2. 用户指定的渠道在 digest channels 中存在
3. 用户表达办理意愿（"办理"/"就这个"/"领X"/"继续"）

渠道匹配示例：
- "领生存金"，digest channels 含 `survival_fund` → 触发
- "领红利"，digest channels 不含 `bonus` → **不触发**，由「保险取款」接管

不满足任一条 → 跳过本技能，由「保险取款」接管。不要输出任何提示语，不要停止对话。

触发示例：
- 选择方案："办理方案1"、"就第一个"、"第一个吧"
- 选择渠道："领生存金"、"办理贷款"、"要红利"
- 按钮触发："办理生存金领取，POL001，12000.00"
- 上轮提交后继续："红利也办一下"、"继续"

不触发（转「保险取款」技能）：
- 咨询类："能取多少"、"帮我规划"
- 方案调整："不要贷款"、"少取一点"、"换个方案"
- 拒绝："不"、"算了"、"再看看" → 不执行，回方案咨询

---

## 渠道 → operation_type 映射表

| 渠道 channel           | operation_type | 中文名   |
|------------------------|----------------|----------|
| `survival_fund`        | `shengcunjin`  | 生存金领取 |
| `bonus`                | `bonus`        | 红利领取   |
| `policy_loan`          | `loan`         | 保单贷款   |
| `partial_withdrawal`   | `partial`      | 部分领取   |
| `surrender`            | `surrender`    | 退保       |

---

## 决策树（必须从上到下逐步执行）

> **绝对禁止**：不经过下面三步就直接调用 `submit_withdrawal`。

### STEP 0 — 续办检查

查看最近的 `submit_withdrawal` 结果：
- 含"还有{X}待办理" 且之后无新方案 digest（`方案: ...`）→ 询问用户是否继续
  - 同意 → STEP 2 | 拒绝 → 结束
- 否则 → STEP 1

### STEP 1 — 渠道计数

读取 `render_a2ui` 工具结果中的方案摘要（digest），找到用户选择的方案，**数 `channels` 字段的数量**。

> **注意**：`channels` 字段已与实际分配保持一致。如果 digest 中某渠道在 channels 里但明细中没有对应金额，说明该渠道无可用额度，不要列出。

digest 格式示例：
```
[已向用户展示卡片] 方案: ★ 推荐: 零成本领取 | channels: ["survival_fund", "bonus"] | 总额: ¥17,200.00 | 生存金 ¥12,000.00, 红利 ¥5,200.00
方案: 保单贷款 | channels: ["policy_loan"] | 总额: ¥20,000.00 | 保单贷款 ¥20,000.00
```

- **1 个渠道** → 跳到 **STEP 2**
- **2+ 个渠道** → 列出渠道让用户选择，**不要调用工具**：
  > "这个方案包含两项，每次办理一项，您想先办理哪个？
  > 1. 生存金领取(¥12,000.00)
  > 2. 红利领取(¥5,200.00)"
  - 等用户回复选择后 → 进入 **STEP 2**

### STEP 2 — 提交

调用：`submit_withdrawal(operation_type=...)`

工具自动生成文案并触发 STOP，只需传 operation_type。

---

## 正例

### 例 1：多渠道方案 — 列出渠道 → 用户选择 → 提交

```
digest: 方案: ★ 推荐: 零成本领取 | channels: ["survival_fund", "bonus"] | 总额: ¥17,200.00 | 生存金 ¥12,000.00, 红利 ¥5,200.00

用户: "就零成本方案"
助手（STEP 1 — 2个渠道，需要问）:
  "这个方案包含两项，每次办理一项，您想先办理哪个？
   1. 生存金领取(¥12,000.00)
   2. 红利领取(¥5,200.00)"

用户: "先领生存金"
助手（STEP 2）:
  → submit_withdrawal(operation_type="shengcunjin")
```

### 例 2：续办 — 上轮提交后用户回来继续

```
上轮 submit_withdrawal 结果: "已启动生存金领取办理流程。还有红利领取(¥5,200.00)待办理"

用户: "红利也办一下"
助手（STEP 0 — 续办）:
  → submit_withdrawal(operation_type="bonus")
```

### 例 3：单渠道方案 — 直接办理

```
digest: 方案: 保单贷款 | channels: ["policy_loan"] | 总额: ¥20,000.00 | 保单贷款 ¥20,000.00

用户: "办理方案2"
助手（STEP 1 — 1个渠道，直接 STEP 2）:
  → submit_withdrawal(operation_type="loan")
```

## 反例（禁止）

### 反例 1：多渠道方案未追问直接提交

```
digest: channels: ["survival_fund", "bonus"]
用户: "就方案一"
❌ 直接调用 submit_withdrawal(operation_type="shengcunjin")
✅ 先列出两个渠道让用户选择，用户选定后再提交
```

### 反例 2：operation_type 映射错误

```
用户: "领生存金"
❌ submit_withdrawal(operation_type="survival_fund")
✅ submit_withdrawal(operation_type="shengcunjin")
```

## 禁止事项

- **禁止**调用 `render_a2ui`
- **禁止**调用 `rule_engine`
- **禁止**自行编造办理成功提示（工具会返回标准回复）
- **禁止**跳过决策树直接调用 `submit_withdrawal`
- **禁止**额外确认环节 — 工具只是唤起流程，后续有独立确认页面
- **禁止**按方案名猜渠道数量 — 必须读 digest 中的 `channels` 字段
