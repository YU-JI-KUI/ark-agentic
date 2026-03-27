---
name: profit_analysis
description: 负责处理所有与"钱的变动"相关的查询，包括盈亏排行、历史收益曲线、逐日收益明细、收益归因以及持有股票的分红事件。
version: "1.0"
invocation_policy: auto
group: securities
tags:
  - profit_analysis
  - profit
  - dividend
required_tools:
  - stock_profit_ranking
  - asset_profit_hist_period
  - asset_profit_hist_range
  - stock_daily_profit_month
  - stock_daily_profit_range
  - security_info_search
  - display_card
---

# 收益与分红分析 (Profit Analysis)

## 1. 核心职责 (Core Responsibilities)

当用户意图属于以下场景时，路由至本 SKILL：

- **收益排行**：查询账户内赚钱或亏钱最多/最少的标的。
- **趋势与历史**：查看特定时段或自定义区间的收益走势曲线。
- **日历明细**：查看某个月份或区间的逐日盈亏情况。
- **分红事件**：查询用户已持有股票的分红派息历史与到账情况。

## 2. 触发关键词 (Trigger Keywords)

盈亏排行, 赚最多, 亏最多, 收益曲线, 历史收益, 每日收益, 某月盈亏, 分红, 派息, 什么时候分红.

## 3. 意图与工具映射 (Intent & Tool Mapping)

> **注意**：调用涉及时间的工具时，必须严格提取用户的**时间语义**。

| 子意图分类 | 业务逻辑说明 | 目标工具及关键参数 |
| :--- | :--- | :--- |
| `RANKING` | 股票盈亏排行 | `stock_profit_ranking(period)` |
| `HIST_CURVE` | 预设时段收益曲线 | `asset_profit_hist_period(period)` |
| `HIST_CURVE_CUSTOM` | 自定义区间收益曲线 | `asset_profit_hist_range(begin_time, end_time)` |
| `DAILY_DETAIL` | 指定月份逐日收益 | `stock_daily_profit_month(month)` |
| `DAILY_DETAIL_CUSTOM` | 自定义区间逐日收益 | `stock_daily_profit_range(begin_time, end_time)` |
| `DIVIDEND_EVENTS` | 已持仓股票分红查询 | `security_info_search(query, include_dividend=True)` |

## 4. 执行约束 (Constraints)

1. **分红查询红线**：当前分红能力**仅限用户已持仓的股票**。如果用户查询未持仓的股票分红（例如全市场搜索），必须明确回复用户当前不支持，禁止编造或产生幻觉。
2. **时间参数枚举 (`period`)**：只允许使用以下枚举值：`this_week`（本周）、`month_to_date`（月初至今）、`year_to_date`（年初至今）、`past_year`（过去一年）、`since_inception`（开户以来）。
3. **输出模式**：
   - 若用户仅查询客观排行/走势，调用 `display_card` 展示。
   - 若用户要求"分析一下为什么亏损"（收益归因），需结合工具返回的 JSON 数据，输出精简、结构化的 Markdown 文本进行总结，禁止输出冗长的套话。
