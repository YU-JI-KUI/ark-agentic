---
name: 保险取款流程（Flow）
description: 通过 5 阶段 SOP 流程处理保险取款：身份核验 → 方案查询 → 方案确认 → 二次确认 → 执行取款。支持跨会话中断恢复。
version: "1.0.0"
invocation_policy: auto
group: insurance
tags:
  - withdrawal
  - insurance
  - flow
  - financial
required_tools:
  - collect_user_fields
  - rollback_flow_stage
  - customer_info
  - policy_query
  - rule_engine
  - render_a2ui
  - submit_withdrawal
  - resume_task
---

# 保险取款流程（Agentic Native Flow）

通过结构化 SOP 处理取款业务，流程由框架自动驱动（无需手动调用评估器）。

## 核心规则

1. **当前阶段状态由框架自动注入**到系统提示词中，请始终以提示词中的「当前流程状态」为准
2. 根据当前阶段的建议工具和阶段参考文档，执行对应的数据收集或操作
3. **工具阶段自动提交**：identity_verify / options_query / execute 阶段的数据由框架在工具执行后自动提取并提交，无需手动操作
4. **用户字段阶段**：plan_confirm 和 double_confirm 阶段需向用户再次收集和确认需要提交的信息
5. 每轮操作完成后，框架将自动重新评估阶段进展

## 异常处理原则

- **工具调用失败**：告知用户具体失败原因，提示稍后重试；不调用 `collect_user_fields`，流程停留在当前阶段，支持重试
- **关键信息缺失**（user_id、身份未认证、无有效保单）：明确告知用户缺失内容，无法继续时终止流程
- **用户中途退出**：若用户明确表示不再继续，停止流程；已完成阶段数据保留，支持后续通过 `resume_task` 恢复

## 流程回退

当用户希望修改已完成阶段的内容（如更换方案、重新查询等）：

1. 查看提示词中「可回退节点」列表（来自 `available_checkpoints`）
2. 根据用户意图找到最合适的回退点：
   - **明确匹配**：告知用户将回退到「XX阶段」重新执行，等待用户确认
   - **无法判断**：将所有可回退节点全部展示，请用户指定
3. 用户确认后调用 `rollback_flow_stage(stage_id=<确认的 stage_id>)`
4. 工具自动清除目标阶段及其后续所有阶段的数据
5. 框架将在下一轮自动重新评估，从目标阶段重新开始执行
