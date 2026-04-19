# 阶段 1：身份核验

## 目标

验证客户身份信息，并获取关联保单列表。

## 操作步骤

1. 调用 `customer_info(user_id=<user_id>, info_type="identity")` 获取客户基础信息：
   - `user_id`：系统用户 ID（根路径）
   - `identity.verified`：实名认证状态（bool）

2. 若 `identity.verified=false`，告知用户需先完成实名认证，流程终止。

3. 调用 `policy_query(user_id=<user_id>, query_type="list")` 获取保单列表。
   - 返回 `policyAssertList`，从中提取每项的 `policy_id`。

## 阶段提交

工具调用完成后，调用 `commit_flow_stage` 提交本阶段：

```
commit_flow_stage(stage_id="identity_verify")
```

> `user_id`、`id_card_verified`、`policy_ids` 三个字段均为 **tool 来源**，
> 框架自动从 `_customer_info_result` 和 `_policy_query_result` 中提取，
> **无需在 user_data 中传递**。

## 完成条件

- `id_card_verified = true`
- `policy_ids` 非空列表

## 异常处理

- 客户信息查询失败 → 提示用户稍后重试，不调用 commit_flow_stage
- 无有效保单 → 告知用户当前无可操作保单，流程终止
