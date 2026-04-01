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

## 4. **输出格式与 UI 协同规范 (UI Coordination)**
  - **禁止数据复述**： 纯查询意图 (Query)：我的总资产是多少？” / “看一下我的 ETF 持仓。调用 `display_card` 展示客观数据（总资产列表、ETF持仓列表、营业部信息），你的文本回复必须极其简短（例如：“为您找到以下持仓信息：”或“您的账户总资产如下：”）。**绝对禁止**在文本中重复打印卡片中完整的数据信息。
  - **边界划分**：分析意图 (Analysis)：“我的 ETF 为什么今天亏了这么多？” / “哪只基金收益最少？“，需结合工具返回的 JSON 数据，输出精简、结构化的 Markdown 文本归因分析，禁止输出冗长的套话。
  
