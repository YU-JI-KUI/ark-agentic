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
  - customer_info
  - policy_query
  - rule_engine
  - render_a2ui
  - submit_withdrawal
  - resume_task
---

# 保险取款流程（Agentic Native Flow）

通过结构化 4 阶段 SOP 处理取款业务，流程由 `withdraw_money_flow_evaluator` 驱动。

## 核心规则

1. **每次回复前必须先调用** `withdraw_money_flow_evaluator` 评估当前阶段
2. 根据 evaluator 返回的 `current_stage.suggested_tools`，按阶段参考文档的操作指引执行
3. 完成阶段业务操作后，再次调用 `withdraw_money_flow_evaluator` 确认阶段完成
4. evaluator 返回 `flow_status=completed` 时流程结束

## 流程总览

| 阶段 | ID | 工具 | wait_for_user |
|------|-----|------|--------------|
| 身份核验 | identity_verify | customer_info, policy_query | 否 |
| 方案查询 | options_query | rule_engine | 否 |
| 方案确认 | plan_confirm | render_a2ui | **是** |
| 执行取款 | execute | submit_withdrawal | 否 |

## 跨会话恢复

用户离开后重新进入时，若检测到未完成的流程：
1. 调用 `resume_task(flow_id=<flow_id>)` 恢复上下文
2. 调用 `withdraw_money_flow_evaluator` 查看当前阶段
3. 按阶段 SOP 继续执行

## state_delta 写入约定

业务工具完成阶段数据后，必须通过 state_delta 点路径写入（勿整体替换 `_flow_context`）：

```python
metadata={"state_delta": {
    "_flow_context.stage_<stage_id>": {
        # 阶段完成数据（见各阶段参考文档）
    }
}}
```
