---
name: holdings_analysis
description: |
  查询、分析用户的持仓情况，包括 ETF、港股通、基金等。
  When to use: 用户想要查看持仓明细、ETF持仓、港股通持仓、基金持仓或询问"我买了什么股票"时使用。
version: "1.0"
invocation_policy: auto
group: securities
tags:
  - holdings
  - asset_holdings
required_tools:
  - etf_holdings
  - hksc_holdings
  - fund_holdings
  - display_card
---

# 用户资产持仓技能

## 一、技能目标

为用户提供资产持仓查询与分析能力，包括：

-   ETF
-   港股通
-   基金理财
-   全部资产组合

支持：

1️⃣ 实时持仓获取\
2️⃣ UI卡片展示\
3️⃣ 数据分析\
4️⃣ 组合分布计算

本技能仅提供客观分析，不提供投资建议。

------------------------------------------------------------------------

## 二、意图模型（用于 Router/Planner）

```yaml
intent_schema:
  asset_type:
    enum:
      - ETF
      - HKSC
      - FUND
      - ALL

  action:
    enum:
      - VIEW          # 仅查看，展示卡片
      - ANALYZE       # 分析，输出 Markdown 报告
      - DISTRIBUTION  # 分布分析
      - TOP_PERFORMER # 找最佳表现
```

### 默认推断规则

| 用户表达       | action        |
| -------------- | ------------- |
| 我的ETF        | VIEW          |
| 看看基金收益   | ANALYZE       |
| 全部持仓分布   | DISTRIBUTION  |
| 哪只表现最好   | TOP_PERFORMER |

------------------------------------------------------------------------

## 三、工具契约

### 数据获取工具

| 工具              | 用途             |
| ----------------- | ---------------- |
| `etf_holdings()`  | 获取 ETF 持仓    |
| `hksc_holdings()` | 获取港股通持仓   |
| `fund_holdings()` | 获取基金持仓     |

### 展示工具

| 工具                            | 用途                   |
| ------------------------------- | ---------------------- |
| `display_card(source_tool="xx")` | 将数据推送至前端显示卡片 |

------------------------------------------------------------------------

## 四、执行状态机

```
    STATE_1_INTENT_PARSE
            ↓
    STATE_2_FETCH_DATA
            ↓
    ┌───────┴───────┐
    ↓               ↓
STATE_3_ANALYSIS   STATE_4_CARD_DISPLAY
(intent.action != VIEW)  (intent.action == VIEW)
```

### STATE_1_INTENT_PARSE

解析用户意图，识别：
- `asset_type`：资产类型（ETF / HKSC / FUND / ALL）
- `action`：操作类型（VIEW / ANALYZE / DISTRIBUTION / TOP_PERFORMER）

### STATE_2_FETCH_DATA（必选）

根据 `asset_type` 调用对应工具：

| 资产类型 | 调用工具         |
| -------- | ---------------- |
| ETF      | `etf_holdings()` |
| HKSC     | `hksc_holdings()`|
| FUND     | `fund_holdings()`|
| ALL      | 全部调用         |

> ⚠️ **严禁从历史对话中提取数值**，必须每次重新调用工具。

### STATE_3_ANALYSIS（条件触发）

**触发条件**：`intent.action != VIEW`

**执行内容**：输出 Markdown 分析报告

分析模块包含：

#### 基础统计

-   总市值
-   总收益
-   收益排序

#### 分布分析

-   资产占比
-   集中度

#### 风险提示

-   大额亏损标记
-   高集中暴露提示

> ⚠️ 禁止生成交易建议

### STATE_4_CARD_DISPLAY（条件触发）

**触发条件**：`intent.action == VIEW`

**执行内容**：

1. 调用 `display_card(source_tool="xxx")` 展示卡片
2. 简短确认回复

**失败处理**：

| 情况       | 行为               |
| ---------- | ------------------ |
| 超时       | 不调用 display_card |
| 空持仓     | `empty=True`       |
| 部分成功   | 显示成功部分       |

------------------------------------------------------------------------

## 五、输出策略

### 查询类（action == VIEW）

简短确认回复，例如："已为您刷新并显示最新的持仓信息。"

> 禁止输出数值摘要或原始 JSON

### 分析类（action != VIEW）

根据工具返回的数据，用 Markdown 格式撰写分析报告，建议包含：

- **持仓列表**：表格形式展示各持仓明细
- **汇总统计**：总市值、总盈亏、收益率等关键指标
- **分析观察**：基于数据的客观描述

### 多类资产对比（DISTRIBUTION）

展示各类资产的市值和占比分布。

------------------------------------------------------------------------

## 六、错误处理策略

| 错误         | 回复                   |
| ------------ | ---------------------- |
| 工具不可用   | 系统繁忙，请稍后重试   |
| 数据为空     | 当前无持仓             |
| 部分失败     | 已显示可获取的数据     |

------------------------------------------------------------------------

## 七、性能与安全约束

-   禁止使用历史对话数据
-   每次必须实时调用工具
-   不泄露工具原始 JSON
-   不提供投资建议
