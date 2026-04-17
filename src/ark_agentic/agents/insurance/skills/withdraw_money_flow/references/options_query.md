# 阶段 2：方案查询

## 目标

查询当前客户所有保单的可取款选项，计算各渠道可用额度。

## 操作步骤

1. 调用 `rule_engine(action="list_options")` 获取所有可用取款方案。

   返回数据结构示例：
   ```json
   {
     "options": [
       {"channel": "survival_fund", "amount": 50000.0, "policy_id": "POL001"},
       {"channel": "bonus", "amount": 20000.0, "policy_id": "POL001"},
       {"channel": "policy_loan", "amount": 80000.0, "policy_id": "POL002"}
     ],
     "total_cash_value": 150000.0,
     "max_withdrawal": 120000.0
   }
   ```

2. 整理 `available_options`、`total_cash_value`、`max_withdrawal`。

## 阶段完成数据（写入 state_delta）

```python
metadata={"state_delta": {
    "_flow_context.stage_options_query": {
        "available_options": [
            {"channel": "survival_fund", "amount": 50000.0, "policy_id": "POL001"},
            # ...
        ],
        "total_cash_value": 150000.0,
        "max_withdrawal": 120000.0,
    }
}}
```

## 完成条件

- `available_options` 非空列表
- `total_cash_value` > 0
- `max_withdrawal` >= 0

## 渠道优先级参考

| 优先级 | 渠道 | 说明 |
|--------|------|------|
| 1 | survival_fund, bonus | 零成本，不影响保障 |
| 2 | policy_loan | 年利率 5%，保障不受影响 |
| 3 | partial_withdrawal | 部分领取，保障有损失 |
| 4 | surrender | 退保，保障终止，最后手段 |
