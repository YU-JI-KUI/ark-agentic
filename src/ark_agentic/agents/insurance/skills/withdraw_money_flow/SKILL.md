---
name: 保险取款流程（Flow）
description: 通过 5 阶段 SOP 处理保险取款：身份核验 → 方案查询 → 方案确认 → 二次确认 → 执行取款。支持跨会话中断恢复。
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
enabled: False
---

# 保险取款流程（Flow）

用户已进入「取款办理」闭环时，按阶段完成核验、算费、交互确认与提交。**每轮发言前**须结合系统提示中的 **`<flow_evaluation>`**（块首为通用 **「流程评估约定」**，块内 fenced JSON 为结构化状态），再按 `<flow_reference>` 做本阶段话术与参数。

---

## 决策依据（流程状态 JSON）

通用行动规则（outstanding、阶段守卫、工具边界）见 `<flow_evaluation>` 内 **「流程评估约定」**。下表仅补充 **JSON 字段语义**（对象在该块内 fenced JSON 中）。

| 字段路径 | 含义与行动 |
|----------|------------|
| `flow_status === "completed"` | 本流程已在系统内闭环结束。 |
| `current_stage` 存在 | 仍在办理中。必须处理完本阶段再进入下一阶段。 |
| `current_stage.result === "invalid"` | `outstanding_fields` 中存在 `status: "error"` 的项。先根据其中的 `error`（及 `hint`）修正数据、重试工具或向用户澄清，**不要**无视错误继续往下走。 |
| `current_stage.result === "incomplete"` | `outstanding_fields` 中为待补数据。对每一项：`hint` 若说明需 `collect_user_fields`，则在和用户确认取值后调用；否则用 `suggested_tools` 中的工具从系统侧补齐。 |
| `outstanding_fields` 为空对象且 `result` 仍为 `incomplete` | 少见；仍遵守 `suggested_tools` 与阶段参考文档，直至下轮 JSON 更新。 |

若在未完成当前阶段时调用了**仅属于后面阶段**的工具，你会收到短小拒绝话术（阶段未完成）；此时应回到上表，先清掉 `outstanding_fields`。

---

## 阶段顺序与参考（`id` 与 JSON 中 `current_stage.id` 一致）

| 顺序 | `id` | 要点 |
|------|------|------|
| 1 | `identity_verify` | `customer_info`、`policy_query`；见 `identity_verify.md` |
| 2 | `options_query` | `rule_engine`；见 `options_query.md` |
| 3 | `plan_confirm` | `render_a2ui` + 用户确认；见 `plan_confirm.md` |
| 4 | `double_confirm` | 用户再次确认；见 `double_confirm.md` |
| 5 | `execute` | `submit_withdrawal`；见 `execute.md` |

各阶段的详细字段、卡片与话术以 `references/` 为准。

---

## 待恢复任务列表（与流程状态 JSON 并列时）

当系统提示中出现 **「检测到未完成的流程任务」** 及 JSON 数组（含 `flow_id`、`task_name` 等）时：

- **必须先向用户说明选项并征得明确答复**，再调用 `resume_task`。
- `flow_id` **必须**来自该数组中的条目。
- 用户表示继续办理 → `resume_task(flow_id="…", action="resume")`；表示放弃/重做 → `resume_task(flow_id="…", action="discard")`。
- 在用户表态前**不要**调用 `resume_task`。

---

## 回退（用户要改已确认内容）

当用户明确要求修改已走过阶段的关键结论（如方案、金额、渠道）：

1. 本流程的 checkpoint 阶段为 **`plan_confirm`**（方案确认）；回退目标一般回到该阶段或用户明确指向的更早阶段。
2. 向用户说明将回退到哪个阶段、会清空哪些后续数据，**得到确认后再**调用 `rollback_flow_stage(stage_id="…")`。
3. `stage_id` 须为**已完成的 checkpoint 阶段 id**（与工具描述一致）；调用后按**新**的状态 JSON 从该阶段继续。

---

## 沟通与风险

- 关键信息不足时，明确告知缺什么，不要虚构数据。
- 敏感操作提示风险；工具只返回纯 `tool_call` 时不要夹带长解释（见全局协议）。
