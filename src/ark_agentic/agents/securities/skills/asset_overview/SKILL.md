---
name: asset_overview
description: 负责处理用户关于账户整体资产状况、大类资产持仓列表（ETF/基金/港股通）、现金余额以及账户/营业部基础信息的查询。
version: "2.0"
invocation_policy: auto
group: securities
tags:
  - asset_overview
  - account
  - holdings
required_tools:
  - account_overview
  - cash_assets
  - etf_holdings
  - hksc_holdings
  - fund_holdings
  - branch_info
  - display_card
---

# 资产与账户总览 (Asset Overview)

## 1. 核心职责 (Core Responsibilities)

当用户意图属于以下场景时，路由至本 SKILL：

- **宏观资产**：总资产、仓位比例、两融净资产及风控指标查询。
- **现金状况**：现金余额、可用资金、可取资金、冻结资金明细。
- **持仓列表**：想知道自己"持有"什么，包括 ETF、港股通、基金/理财的持仓列表与分布。
- **账户属性**：查询开户营业部名称、地址、客服电话或席位号。

## 2. 触发关键词 (Trigger Keywords)

总资产, 账户情况, 仓位, 现金, 可用资金, 冻结, ETF持仓, 港股持仓, 我的基金, 营业部, 在哪开的户.

## 3. 意图与工具映射 (Intent & Tool Mapping)

| 子意图分类 | 业务逻辑说明 | 目标工具 |
| :--- | :--- | :--- |
| `TOTAL_OVERVIEW` | 账户整体资产及两融指标 | `account_overview` |
| `CASH_STATUS` | 现金、可用、可取及冻结明细 | `cash_assets` |
| `HOLDINGS_ETF` | ETF 持仓列表与市值 | `etf_holdings` |
| `HOLDINGS_HKSC` | 港股通持仓列表与市值 | `hksc_holdings` |
| `HOLDINGS_FUND` | 基金理财持仓列表与市值 | `fund_holdings` |
| `ACCOUNT_INFO` | 营业部及账户属性 | `branch_info` |

## 4. 执行约束 (Constraints)

1. **纯数据呈现**：对于以上工具的查询结果，请直接调用后处理工具 `display_card` 推送前端卡片，不要擅自对数据进行长篇大论的文字解读，除非用户明确要求解释某个字段。
2. **边界划分**：如果用户不仅问了"我持有多少"，还问了"哪只赚得最多"或"为什么亏损"，请立即将控制权交接或路由给 `profit_analysis` SKILL。
