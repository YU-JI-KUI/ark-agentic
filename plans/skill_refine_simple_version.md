Python Agentic 开发环境以及追求“简单、实用、拒绝过度设计”的工程理念，我为你整理了这套高度收敛的 `SKILL.md` 模板。

在 Python 体系的 Agent 框架中，`SKILL.md` 通常直接作为大模型 Prompt 的一部分被加载（System Message）。因此，结构上我们要做到**高信噪比**、**意图路由清晰**，以有效提升“领域意图识别率”并降低“端到端延迟”。

以下是推荐的目录树及核心 SKILL 定义：

```text
src/ark_agentic/agents/securities/skills/
├── asset_overview/
│   └── SKILL.md        # 核心1：宏观资产与账户现状
├── profit_analysis/
│   └── SKILL.md        # 核心2：收益、排行与分红归因
└── security_detail/
    └── SKILL.md        # 预留占位（当前未实现，保持文档空置或仅写TODO）
```

---

### 1. `asset_overview/SKILL.md` (资产与账户总览)

这个技能合并了所有的“现状查询”能力，避免了在“总资产”和“持仓”之间发生路由跳跃。

```markdown
---
name: asset_overview
description: 负责处理用户关于账户整体资产状况、大类资产持仓列表（ETF/基金/港股通）、现金余额以及账户/营业部基础信息的查询。
---

# 资产与账户总览 (Asset Overview)

## 1. 核心职责 (Core Responsibilities)
当用户意图属于以下场景时，路由至本 SKILL：
- **宏观资产**：总资产、仓位比例、两融净资产及风控指标查询。
- **现金状况**：现金余额、可用资金、可取资金、冻结资金明细。
- **持仓列表**：想知道自己“持有”什么，包括 ETF、港股通、基金/理财的持仓列表与分布。
- **账户属性**：查询开户营业部名称、地址、客服电话或席位号。

## 2. 触发关键词 (Trigger Keywords)
总资产, 账户情况, 仓位, 现金, 可用资金, 冻结, ETF持仓, 港股持仓, 我的基金, 营业部, 在哪开的户.

## 3. 意图与工具映射 (Intent & Tool Mapping)
| 子意图分类 | 业务逻辑说明 | 目标工具 |
| :--- | :--- | :--- |
| `TOTAL_OVERVIEW` | 账户整体资产及两融指标 | `account_overview` |
| `CASH_STATUS` | 现金、可用、可取及冻结明细 | `cash_assets` |
| `HOLDINGS_ETF` | ETF持仓列表与市值 | `etf_holdings` |
| `HOLDINGS_HKSC` | 港股通持仓列表与市值 | `hksc_holdings` |
| `HOLDINGS_FUND` | 基金理财持仓列表与市值 | `fund_holdings` |
| `ACCOUNT_INFO` | 营业部及账户属性 | `branch_info` |

## 4. 执行约束 (Constraints)
1. **纯数据呈现**：对于以上工具的查询结果，请直接调用后处理工具 `display_card` 推送前端卡片，不要擅自对数据进行长篇大论的文字解读，除非用户明确要求解释某个字段。
2. **边界划分**：如果用户不仅问了“我持有多少”，还问了“哪只赚得最多”或“为什么亏损”，请立即将控制权交接或路由给 `profit_analysis` SKILL。
```

---

### 2. `profit_analysis/SKILL.md` (收益与分红分析)

这个技能是整个券商 Agent 的计算和逻辑重灾区，通过 Pydantic 或类似的 Schema 强约束时间参数是关键。

```markdown
---
name: profit_analysis
description: 负责处理所有与“钱的变动”相关的查询，包括盈亏排行、历史收益曲线、逐日收益明细、收益归因以及持有股票的分红事件。
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
| `DAILY_DETAIL_CUSTOM`| 自定义区间逐日收益 | `stock_daily_profit_range(begin_time, end_time)` |
| `DIVIDEND_EVENTS` | 已持仓股票分红查询 | `security_info_search(query, include_dividend=True)` |

## 4. 执行约束 (Constraints)
1. **分红查询红线**：当前分红能力**仅限用户已持仓的股票**。如果用户查询未持仓的股票分红（例如全市场搜索），必须明确回复用户当前不支持，禁止编造或产生幻觉。
2. **时间参数枚举 (`period`)**：只允许使用以下枚举值：`this_week` (本周), `month_to_date` (月初至今), `year_to_date` (年初至今), `past_year` (过去一年), `since_inception` (开户以来)。
3. **输出模式**：
   - 若用户仅查询客观排行/走势，调用 `display_card` 展示。
   - 若用户要求“分析一下为什么亏损”（收益归因），需结合工具返回的 JSON 数据，输出精简、结构化的 Markdown 文本进行总结，禁止输出冗长的套话。
```

---

### 设计收益点总结
这种扁平化的 Markdown 结构对 LLM 的上下文窗口非常友好：
1. **Zero-Shot 友好**：明确的 `Constraints` (约束) 列表能有效降低大模型在调用复杂工具（尤其是时间参数和分红边界）时的幻觉率。
2. **解耦可视化**：将 `display_card` 统一规定为后置动作，避免了每个意图里都要重复写“怎么展示卡片”的啰嗦代码，符合你推崇的“无冗余设计”。
