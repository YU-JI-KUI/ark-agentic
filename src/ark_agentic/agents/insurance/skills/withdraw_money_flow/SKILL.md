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

1. **Flow Evaluation 消息是流程决策的核心依据** — 每轮 LLM 调用前，框架自动运行 `before_model_flow_eval` hook，生成一条 `role="system"` 的独立消息（`## Flow Evaluation`），包含：
   - `stages_overview`：各阶段状态（completed / in_progress / pending）
   - `current_stage`：当前阶段 ID、字段状态（collected / missing / error）、建议工具
   - 每轮必须**先读取该消息**，再决定下一步操作
2. **统一评估-提交机制** — 所有字段的抽取、Pydantic 校验和阶段提交均在 `evaluate()` 中统一完成，不存在工具执行后自动提交的 hook
   - 有 `state_key` 的字段：evaluator 自动从 session.state 提取
   - 无 `state_key` 的字段：LLM 通过 `collect_user_fields` 写入暂存区，由**下一轮 evaluate()** 统一校验和提交
   - 字段全部就绪且校验通过时，evaluator 自动提交并推进阶段
3. **阻断机制** — 当 Pydantic 校验失败时，框架直接阻断 LLM 调用（`block_model=True`），返回固定话术（如「XX信息获取失败，是否需要重试？」），LLM 不会收到用户输入，也无法生成回复
4. 根据当前阶段的 `suggested_tools` 和阶段参考文档，执行对应的数据收集或操作
5. `collect_user_fields` 只写入暂存区，不直接触发提交 — 下一轮 evaluate() 会从暂存区读取并统一处理

## 异常处理原则

- **关键信息缺失**：明确告知用户缺失内容，无法继续时终止流程
- **用户中途退出**：若用户明确表示不再继续，停止流程；已完成阶段数据保留，支持后续通过 `resume_task` 恢复

## 流程恢复与放弃

当 Flow Evaluation 消息中出现「未完成的取款流程」JSON 列表时，必须先与用户确认处理方式，再调用 `resume_task`：

| 用户意图 | 调用方式 | 框架行为 |
|----------|----------|----------|
| 继续之前的流程 | `resume_task(flow_id="<JSON 中的 flow_id>", action="resume")` | 恢复 `_flow_context`，按原阶段继续 |
| 放弃 / 重新开始 | `resume_task(flow_id="<JSON 中的 flow_id>", action="discard")` | 从 `active_tasks.json` 中**永久删除**该任务记录，下一轮可发起新流程 |

注意事项：

1. **必须**用 JSON 列表中的 `flow_id`
2. 在用户尚未明确表态前，**不要**自行调用 `resume_task`；持续向用户呈现 JSON 列表中的任务，引导用户做出选择
3. 若用户说"重新开始"/"忘掉之前的"/"取消" → 优先视为 `discard`；说"接着办"/"继续"/"恢复" → 视为 `resume`
4. discard 成功后，下一轮 Flow Evaluation 会自动初始化新的 `_flow_context` 进入 `identity_verify`，无需额外操作

## 流程回退

当用户希望修改已完成阶段的内容（如更换方案、重新查询等）：

1. 查看 Flow Evaluation 消息中的 `available_checkpoints` 列表
2. 根据用户意图找到最合适的回退点：
   - **明确匹配**：告知用户将回退到「XX阶段」重新执行，等待用户确认
   - **无法判断**：将所有可回退节点全部展示，请用户指定
3. 用户确认后调用 `rollback_flow_stage(stage_id=<确认的 stage_id>)`
4. 工具自动清除目标阶段及其后续所有阶段的数据
5. 下一轮 Flow Evaluation 自动重新评估，从目标阶段重新开始执行
