# 阶段 4：执行取款

## 目标

提交取款操作，等待系统处理结果，并向用户展示执行状态。

## 操作步骤

1. 从 `_flow_context.stage_plan_confirm` 读取用户确认的方案：
   - `selected_option.channels`：取款渠道列表
   - `amount`：取款金额

2. 调用 `submit_withdrawal(channels=[...], amount=<amount>)`。

   返回示例：
   ```json
   {
     "transaction_id": "TXN20260417001",
     "status": "submitted",
     "message": "取款申请已提交，预计 1-3 个工作日到账。"
   }
   ```

3. 向用户告知执行结果（一句话，含金额和预计到账时间）。

## 阶段完成数据（写入 state_delta）

```python
metadata={"state_delta": {
    "_flow_context.stage_execute": {
        "transaction_id": "TXN20260417001",
        "status": "submitted",
    }
}}
```

4. 调用 `withdraw_money_flow_evaluator` → 返回 `flow_status=completed` → 流程结束。

## 完成条件

- `transaction_id` 非空
- `status` 为 `"submitted"` 或 `"pending"`（非 `"failed"`）

## 异常处理

- `status = "failed"` → 告知用户失败原因，不写入 state_delta（流程停在 execute 阶段，可重试）
- 网络超时 → 提示用户稍后查询取款状态，不写入 state_delta

## 输出约束

- 禁止用 Markdown 表格展示金额明细
- 若需展示取款凭证，调用 `render_a2ui` 渲染 WithdrawSummaryHeader 卡片
- 回复文字 ≤ 30 字
