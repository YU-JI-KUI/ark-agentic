# 阶段 4：二次确认

## 目标

在执行取款前向用户展示完整的操作摘要，要求用户再次明确确认，防止误操作。

## 操作步骤

1. 调用 `render_a2ui` 展示取款摘要卡片（WithdrawSummaryHeader），内容包含：
   - 取款总金额
   - 所选渠道明细
   - 预计到账时间（1-3 个工作日）

2. 用文字告知用户：**此操作不可撤销**，请再次确认是否继续。

3. 等待用户明确回复后，调用 `collect_user_fields(fields={"double_confirm": true/false})`：
   - 用户确认（"确认"/"是"/"没问题"/"办理"等）→ `double_confirm: true`
   - 用户拒绝或犹豫 → `double_confirm: false`，不调用 collect_user_fields，询问用户意图

## 异常处理

- 用户拒绝或取消 → 询问是否需要修改方案（可回退到 plan_confirm），不调用 collect_user_fields
- `render_a2ui` 失败 → 以文字描述摘要内容，继续等待用户确认
