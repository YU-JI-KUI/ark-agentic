# 阶段 1：身份核验

## 目标

验证客户身份信息，并获取关联保单列表。

## 操作步骤

1. 调用 `customer_info(user_id=<user_id>, info_type="identity")` 获取客户基础信息：

2. 若 `identity.verified=false`，告知用户需先完成实名认证，流程终止。

3. 调用 `policy_query(user_id=<user_id>, query_type="list")` 获取保单列表。

## 异常处理

- 客户信息查询失败 → 提示用户稍后重试，不调用 commit_flow_stage
- 无有效保单 → 告知用户当前无可操作保单，流程终止
