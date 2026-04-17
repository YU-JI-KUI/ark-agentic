# 阶段 1：身份核验

## 目标

验证客户身份信息，并获取关联保单列表。

## 操作步骤

1. 调用 `customer_info(action="basic")` 获取客户基础信息：
   - `user_id`：系统用户 ID
   - `id_card_verified`：实名认证状态（bool）

2. 若 `id_card_verified=false`，告知用户需先完成实名认证，流程终止。

3. 调用 `policy_query(action="list")` 获取保单列表，提取 `policy_ids`。

## 阶段完成数据（写入 state_delta）

```python
metadata={"state_delta": {
    "_flow_context.stage_identity_verify": {
        "user_id": "<user_id>",
        "id_card_verified": True,
        "policy_ids": ["POL001", "POL002"],
    }
}}
```

## 完成条件

- `id_card_verified = true`
- `policy_ids` 非空列表

## 异常处理

- 客户信息查询失败 → 提示用户稍后重试，不写入 state_delta
- 无有效保单 → 告知用户当前无可操作保单，流程终止
