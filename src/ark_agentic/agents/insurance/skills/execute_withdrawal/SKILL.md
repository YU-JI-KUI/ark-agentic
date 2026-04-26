---
enabled: True
name: 取款执行
description: 当最近一次 render_a2ui tool 结果 digest 以 `[卡片:方案` 开头（WithdrawPlanCard 已展示），且用户明确选择该方案中的某一渠道办理时，用本技能调用 submit_withdrawal。只有 `[卡片:总览/…]` 或无 A2UI 历史时本技能不适用，由「保险取款」接管。
version: "10.0.0"
invocation_policy: auto
group: insurance
tags:
  - withdrawal
  - execute
required_tools:
  - submit_withdrawal
---

# 取款执行技能

调用 `submit_withdrawal` 唤起办理流程。工具自动从方案 state 获取保单和金额，**LLM 只传 `operation_type`**。工具返回结构化 digest `[办理:已提交 channel=… remaining=[…]]`，供后续续办判定。

## 触发门禁（硬性，同时满足才启用）

1. 最近一次 `render_a2ui` 结果 digest 以 `[卡片:方案` 开头（兼容旧格式 `[已向用户展示卡片] 方案:`）
2. 用户消息表达办理意愿："办理"、"就…方案"、"领X"、"继续"、按钮文本 query
3. 用户指定的渠道 ∈ 该 digest 的 `channels=[…]` 列表

任一不满足 → **不加载本技能，不调用工具，不回复**，由「保险取款」接管。

不触发举例：
- digest 仅 `[卡片:总览/…]` → 由「保险取款」生成方案卡
- 用户说"不要贷款"、"换个方案" → ADJUST，由「保险取款」处理
- 用户说"能取多少"、"帮我看看" → SUMMARY，由「保险取款」处理
- 用户说"不"、"算了"、"再看看" → 结束，不调用工具

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

最近一次 `submit_withdrawal` 结果 digest 的 `remaining=[…]` **非空** 且 之后没有新 `[卡片:方案` digest：
- 用户同意（"继续"/"红利也办"/"贷款也办"） → STEP 2
- 用户拒绝 → 结束

否则 → STEP 1。

### STEP 1 — 渠道计数

读取最近 `[卡片:方案` digest 的 `channels=[…]` 字段长度。该字段是引擎按**实际分配结果**反推的真实渠道列表（不是 LLM 当初传入的 channels 数组），所以一定可信。

digest 格式示例：
```
[卡片:方案 title="★ 推荐: 零成本领取" channels=[survival_fund,bonus] total=17200.00] 生存金 ¥12,000.00 · 红利 ¥5,200.00
[卡片:方案 title="组合领取方案" channels=[bonus,partial_withdrawal] total=10000.00] 红利 ¥5,200.00 · 部分领取 ¥4,800.00
[卡片:方案 title="★ 推荐: 生存金领取" channels=[survival_fund] total=10000.00] 生存金 ¥10,000.00
```

> 注意：LLM 传给 render_a2ui 的 channels 可能比 digest 多——引擎只在 channels 中真正参与分配的部分会出现在 digest 里。例如 LLM 传 `channels=[survival_fund,bonus,policy_loan]` 但 target=10000 被 survival_fund 单渠道吞掉，digest 只会显示 `channels=[survival_fund]`。**永远以 digest 为准**。

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
digest: [卡片:方案 title="★ 推荐: 零成本领取" channels=[survival_fund,bonus] total=17200.00] 生存金 ¥12,000.00 · 红利 ¥5,200.00

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
上轮 submit_withdrawal digest: [办理:已提交 channel=survival_fund remaining=[bonus]]

用户: "红利也办一下"
助手（STEP 0 — remaining 非空，续办）:
  → submit_withdrawal(operation_type="bonus")
```

### 例 3：单渠道方案 — 直接办理

```
digest: [卡片:方案 title="保单贷款" channels=[policy_loan] total=20000.00] 保单贷款 ¥20,000.00

用户: "办理方案2"
助手（STEP 1 — 1个渠道，直接 STEP 2）:
  → submit_withdrawal(operation_type="loan")
```

## 反例（禁止）

### 反例 1：多渠道方案未追问直接提交

```
digest: [卡片:方案 … channels=[survival_fund,bonus] …]
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

### 反例 3：把总览卡当方案卡触发

```
digest: [卡片:总览/板块 name=zero_cost total=17200.00] 零成本领取 · 生存金(XXX) ¥12,000.00
用户: "领生存金"
❌ 加载本技能并调用 submit_withdrawal（会因 _plan_allocations 空报错）
✅ 不加载本技能，由「保险取款」接管：先 rule_engine + render_a2ui 生成 PlanCard
```

## 禁止事项

- **禁止**调用 `render_a2ui`
- **禁止**调用 `rule_engine`
- **禁止**自行编造办理成功提示（工具会返回标准回复）
- **禁止**跳过决策树直接调用 `submit_withdrawal`
- **禁止**额外确认环节 — 工具只是唤起流程，后续有独立确认页面
- **禁止**按方案名/总览卡片猜渠道数量 — 必须读 `[卡片:方案` digest 的 `channels=[…]` 字段
