---
name: 保险取款流程（Flow）
description: 通过 4 阶段 SOP 流程处理保险取款：身份核验 → 方案查询 → 方案确认 → 执行取款。支持跨会话中断恢复。
version: "1.0.0"
invocation_policy: auto
group: insurance
tags:
  - withdrawal
  - insurance
  - flow
  - financial
required_tools:
  - withdraw_money_flow_evaluator
  - commit_flow_stage
  - customer_info
  - policy_query
  - rule_engine
  - render_a2ui
  - submit_withdrawal
  - resume_task
enabled: False
---

# 保险取款流程（Agentic Native Flow）

通过结构化 4 阶段 SOP 处理取款业务，流程由 `withdraw_money_flow_evaluator` 驱动。

## 核心规则

1. **每次回复前先调用** `withdraw_money_flow_evaluator` 评估当前阶段
2. 根据 evaluator 返回的 `current_stage.suggested_tools`，按阶段参考文档的操作指引执行
3. 若 evaluator 响应包含 `user_required_fields`，需向用户展示方案并收集对应字段
4. 收集完成后调用 `commit_flow_stage(stage_id=<stage_id>, user_data={...})` 提交阶段数据
5. 再次调用 `withdraw_money_flow_evaluator` 确认阶段推进
6. evaluator 返回 `flow_status=completed` 时流程结束

## 流程总览

| 阶段 | ID | 工具 | 字段来源 |
|------|-----|------|---------|
| 身份核验 | identity_verify | customer_info, policy_query | 全部 tool |
| 方案查询 | options_query | rule_engine | 全部 tool |
| 方案确认 | plan_confirm | render_a2ui | 全部 user（需从用户收集） |
| 执行取款 | execute | submit_withdrawal | 全部 tool |

## 跨会话恢复

用户离开后重新进入时，若检测到未完成的流程：
1. 调用 `resume_task(flow_id=<flow_id>)` 恢复上下文
2. 调用 `withdraw_money_flow_evaluator` 查看当前阶段
3. 按阶段 SOP 继续执行

## commit_flow_stage 使用约定

每个阶段的业务工具调用完成后，调用 `commit_flow_stage` 提交阶段数据：

- **tool 来源字段**（如 `user_id`、`available_options`）：框架自动从 session.state 提取，**无需传递**
- **user 来源字段**（如 `confirmed`、`amount`）：必须通过 `user_data` 参数提供

各阶段的字段来源详见对应阶段参考文档。
