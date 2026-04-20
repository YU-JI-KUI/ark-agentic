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
  - rollback_flow_stage
  - customer_info
  - policy_query
  - rule_engine
  - render_a2ui
  - submit_withdrawal
  - resume_task
---

# 保险取款流程（Agentic Native Flow）

通过结构化 SOP 处理取款业务，流程由 `withdraw_money_flow_evaluator` 驱动。

## 核心规则

1. **每次回复前先调用** `withdraw_money_flow_evaluator` 评估当前阶段
2. 根据 evaluator 返回的 `current_stage.suggested_tools`，按阶段参考文档的操作指引执行
3. 若 evaluator 响应包含 `user_required_fields`，需向用户展示方案并收集对应字段
4. 收集完成后调用 `commit_flow_stage(stage_id=<stage_id>, user_data={...})` 提交阶段数据
5. 再次调用 `withdraw_money_flow_evaluator` 确认阶段推进，直至所有阶段完成。

各阶段的字段来源和异常处理详见对应阶段参考文档。

## 异常处理原则

- **工具调用失败**：告知用户具体失败原因，提示稍后重试；不调用 `commit_flow_stage`，流程停留在当前阶段，支持重试
- **关键信息缺失**（user_id、身份未认证、无有效保单）：明确告知用户缺失内容，无法继续时终止流程
- **用户中途退出**：若用户明确表示不再继续，停止流程；已完成阶段数据保留，支持后续通过 `resume_task` 恢复

## 流程回退

当用户希望修改已完成阶段的内容（如更换方案、重新查询等）：

1. 查看 evaluator 响应中的 `available_checkpoints` 列表
2. 根据用户意图找到最合适的回退点：
   - **明确匹配**：告知用户将回退到「XX阶段」重新执行，等待用户确认
   - **无法判断**：将 `available_checkpoints` 列表全部展示，请用户指定
3. 用户确认后调用 `rollback_flow_stage(stage_id=<确认的 stage_id>)`
4. 工具自动清除目标阶段及其后续所有阶段的数据
5. 再次调用 `withdraw_money_flow_evaluator`，从目标阶段重新开始执行
