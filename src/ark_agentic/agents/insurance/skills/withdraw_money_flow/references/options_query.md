# 阶段 2：方案查询

## 目标

查询当前客户所有保单的可取款选项，计算各渠道可用额度。

## 操作步骤

1. 调用 `rule_engine(action="list_options", user_id=<user_id>)` 获取所有可用取款方案。

   返回数据结构关键字段：
   ```json
   {
     "options": [
       {"policy_id": "POL001", "survival_fund_amt": 0, "bonus_amt": 0, ...},
       {"policy_id": "POL002", "survival_fund_amt": 12000, "bonus_amt": 5200, ...}
     ],
     "total_available_excl_loan": 150000.0,
     "total_available_incl_loan": 180000.0
   }
   ```

2. 整理方案，向用户简要说明可取渠道和大致金额范围。

## 阶段提交

工具调用完成后，调用 `commit_flow_stage` 提交本阶段：

```
commit_flow_stage(stage_id="options_query")
```

> `available_options`、`total_cash_value`、`max_withdrawal` 均为 **tool 来源**，
> 框架自动从 `_rule_engine_result` 中提取（含字段重命名）：
> - `available_options` ← `options`
> - `total_cash_value` ← `total_available_excl_loan`
> - `max_withdrawal` ← `total_available_incl_loan`
>
> **无需在 user_data 中传递**。

## 完成条件

- `available_options` 非空列表
- `total_cash_value` > 0

## 渠道优先级参考

| 优先级 | 渠道 | 说明 |
|--------|------|------|
| 1 | survival_fund_amt, bonus_amt | 零成本，不影响保障 |
| 2 | loan_amt | 年利率 5%，保障不受影响 |
| 3 | refund_amt（部分领取） | 部分领取，保障有损失 |
| 4 | refund_amt（退保） | 退保，保障终止，最后手段 |
