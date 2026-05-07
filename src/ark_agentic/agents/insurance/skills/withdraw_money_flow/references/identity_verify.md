# 阶段 1：身份核验

## 目标

验证客户身份信息，并获取关联保单列表。

## 操作步骤

1. 调用 `customer_info(user_id=<user_id>, info_type="full")` **一次性**拉取身份与联系方式（以及本接口在 full 下返回的其它块）。**禁止**拆成先 `identity` 再 `contact`：每次工具返回会**整份覆盖** `session.state._customer_info_result`，后一次调用会丢掉前一次的 `identity`/`contact`，导致流程评估抽不到字段。若无法获取用户基础信息，则客户信息查询失败，流程终止。

2. 若 `identity.verified=false`，告知用户需先完成实名认证，流程终止。

3. 调用 `policy_query(user_id=<user_id>, query_type="list")` 获取保单列表。若返回无有效保单（列表为空或无可操作项），告知用户并**终止本流程**。

## 异常处理

- 客户信息查询失败或用户实名认证失败 → 提示用户稍后重试；框架不会自动提交失败的阶段。
- 无有效保单 → 告知用户当前无可操作保单，终止本流程。
- 工具可达但评估侧仍报字段缺失 → 按系统提示 `<flow_evaluation>` 内通用约定处理，不与「查询失败终止」混为一谈。
