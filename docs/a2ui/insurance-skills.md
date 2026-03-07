# 保险取款场景三技能说明

取款相关技能：clarify_need、withdraw_money、rewrite_plan。便于后续维护与模型匹配。

## 技能分工

### clarify_need

- **触发**：取款意图 + **未**明确金额。
- **职责**：合规采集金额/用途/紧急程度，**不**做方案计算与展示。
- **出口**：信息齐全后交接 withdraw_money。

### withdraw_money

- **触发**：取款意图 + **已**明确金额（或由 clarify_need 交接）。
- **职责**：customer_info → rule_engine(list_options) → **render_card(withdraw_summary)** 作为主呈现 → 可选文字/备选 → 引导确认。
- **不触发**：未明确金额（应先 clarify_need）。

### rewrite_plan

- **触发**：用户对**已推荐方案**提出修改（改金额/改渠道/改单笔等）。
- **职责**：判断 A/B/C → 重调 rule_engine 或 calculate_detail → **render_card(withdraw_summary)** 展示调整后汇总（类型 C 若未刷新 list_options 则仅文字）→ 对比/备选/确认。
- **不触发**：首次取款方案（应由 withdraw_money 处理）。

## 互斥与顺序

- clarify_need 与 withdraw_money 按「是否已有金额」二选一。
- rewrite_plan 仅在「已有过方案推荐」之后可能触发。
- 同一轮中「展示取款汇总」只由 withdraw_money 或 rewrite_plan 之一完成，且均通过同一 A2UI 取款汇总卡片，避免重复与不一致。
