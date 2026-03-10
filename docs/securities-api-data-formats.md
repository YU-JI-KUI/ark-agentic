# 证券 Agent 后端接口数据格式文档

> 本文档描述证券 Agent 所有接口经过 `field_extraction → template_renderer` 处理后，推送至前端的最终 JSON 数据格式。

---

## 数据流

```
原始 API 响应
    │
    ▼
field_extraction.py   ← 按路径提取/整体透传原始字段，清洗电话等格式
    │
    ▼
display_card.py       ← 注入 title（含脱敏账号）
    │
    ▼
template_renderer.py  ← 组装最终 JSON，data 内注入 template 冗余字段
    │
    ▼
前端收到的 ui_data（template + data）
```

---

## 公共约定

- 所有模板顶层字段均为 `template`（字符串）和 `data`（对象）。
- `data.template` 与顶层 `template` 值相同，方便前端在仅持有 `data` 引用时仍能识别模板类型。
- `data.title` 由后端构造，账号经过脱敏处理（保留前 3 位和后 4 位，中间替换为 `****`）。
- 金额字段均为字符串类型，前端负责格式化显示。

---

## 1. 账户总览 `account_overview_card`

### 普通账户（`account_type: "normal"`）

`assetData` 字段：

| 字段路径 | 类型 | 原始 API 路径 | 说明 |
|---|---|---|---|
| `totalAssetVal` | string | `results.rmb.totalAssetVal` | 总资产 |
| `positions` | string | `results.rmb.positions` | 仓位比例，如 `"23.16%"` |
| `prudentPositions` | string | `results.rmb.prudentPositions` | 稳健仓位（通常为空）|
| `mktAssetsInfo.totalMktVal` | string | `results.rmb.mktAssetsInfo.totalMktVal` | 股票证券市值 |
| `mktAssetsInfo.totalMktProfitToday` | string | `results.rmb.mktAssetsInfo.totalMktProfitToday` | 今日收益（负值带 `-` 前缀）|
| `mktAssetsInfo.totalMktYieldToday` | string | `results.rmb.mktAssetsInfo.totalMktYieldToday` | 今日收益率（小数，如 `"-0.01"` 表示 -1%）|
| `fundMktAssetsInfo.fundMktVal` | string | `results.rmb.fundMktAssetsInfo.fundMktVal` | 基金理财市值 |
| `cashGainAssetsInfo.cashBalance` | string | `results.rmb.cashGainAssetsInfo.cashBalance` | 现金余额 |

普通账户完整示例（Mock）：

```json
{
  "template": "account_overview_card",
  "data": {
    "template": "account_overview_card",
    "title": "资金账号：331****2926的资产信息",
    "account_type": "normal",
    "assetData": {
      "totalAssetVal": "390664059.82",
      "positions": "23.16%",
      "prudentPositions": "",
      "mktAssetsInfo": {
        "totalMktVal": "267887813.40",
        "totalMktProfitToday": "-54638.28",
        "totalMktYieldToday": "-0.01"
      },
      "fundMktAssetsInfo": {
        "fundMktVal": "1323481.54"
      },
      "cashGainAssetsInfo": {
        "cashBalance": "1227455354.88"
      }
    }
  }
}
```

### 两融账户（`account_type: "margin"`）

在普通账户字段基础上，`assetData` 额外包含 `rzrqAssetsInfo`（整体透传原始 API 结构）：

| 字段路径 | 类型 | 原始 API 路径 | 说明 |
|---|---|---|---|
| `rzrqAssetsInfo.netWorth` | string | `results.rmb.rzrqAssetsInfo.netWorth` | 净资产 |
| `rzrqAssetsInfo.totalLiabilities` | string | `results.rmb.rzrqAssetsInfo.totalLiabilities` | 总负债 |
| `rzrqAssetsInfo.mainRatio` | string | `results.rmb.rzrqAssetsInfo.mainRatio` | 维持担保比例 |

> 两融账户的 `fundMktAssetsInfo` 通常为 `null`（无基金理财持仓）。

两融账户完整示例（Mock）：

```json
{
  "template": "account_overview_card",
  "data": {
    "template": "account_overview_card",
    "title": "资金账号：331****2926的资产信息",
    "account_type": "margin",
    "assetData": {
      "totalAssetVal": "333678978.13",
      "positions": "70.03%",
      "prudentPositions": "",
      "mktAssetsInfo": {
        "totalMktVal": "233663910.00",
        "totalMktProfitToday": "-1420880.00",
        "totalMktYieldToday": "-0.42"
      },
      "fundMktAssetsInfo": null,
      "cashGainAssetsInfo": {
        "cashBalance": "100815068.13"
      },
      "rzrqAssetsInfo": {
        "netWorth": "332733488.56",
        "totalLiabilities": "945497.57",
        "mainRatio": "35291.35"
      }
    }
  }
}
```

---

## 2. 现金资产 `cash_assets_card`

> **格式说明**：生效格式为 `cash_assets/normal_user.json` 和 `cash_assets/margin_user.json`（`status/results/rmb` 结构）。`cash_assets/default.json` 为旧格式（`code/data` 结构），已废弃，不被当前 `CASH_ASSETS_FIELD_MAPPING` 读取。

### 字段说明

| 字段 | 类型 | 原始 API 路径 | 说明 |
|---|---|---|---|
| `cash_balance` | string | `results.rmb.cashBalance` | 现金总额 |
| `cash_available` | string | `results.rmb.available` | 可用资金 |
| `draw_balance` | string | `results.rmb.avaliableDetail.drawBalance` | 可取资金 |
| `today_profit` | string | `results.rmb.avaliableDetail.cashBalanceDetail.dayProfit` | 今日收益（现金宝）|
| `accu_profit` | string | `results.rmb.avaliableDetail.cashBalanceDetail.accuProfit` | 累计收益（现金宝）|
| `fund_name` | string | `results.rmb.avaliableDetail.cashBalanceDetail.fundName` | 理财产品名称 |
| `fund_code` | string | `results.rmb.avaliableDetail.cashBalanceDetail.fundCode` | 理财产品代码 |
| `frozen_funds_total` | string | `results.rmb.frozenFundsTotal` | 冻结资金总额 |
| `frozen_funds_detail` | array | `results.rmb.frozenFundsDetail` | 冻结资金明细列表 |
| `in_transit_asset_total` | string\|null | `results.rmb.inTransitAssetTotal` | 在途资产总额 |

`frozen_funds_detail` 列表项结构：

```json
{
  "name": "stockFreeze",
  "value": "2000.00",
  "chineseDesc": "股票交易冻结"
}
```

### 普通账户示例（Mock）

```json
{
  "template": "cash_assets_card",
  "data": {
    "template": "cash_assets_card",
    "cash_balance": "50000.00",
    "cash_available": "48000.00",
    "draw_balance": "45000.00",
    "today_profit": "15.50",
    "accu_profit": "1250.00",
    "fund_name": "现金宝",
    "fund_code": "970172",
    "frozen_funds_total": "2000.00",
    "frozen_funds_detail": [
      { "name": "stockFreeze", "value": "2000.00", "chineseDesc": "股票交易冻结" }
    ],
    "in_transit_asset_total": null
  }
}
```

### 两融账户示例（Mock）

结构与普通账户完全相同，数值不同：

```json
{
  "template": "cash_assets_card",
  "data": {
    "template": "cash_assets_card",
    "cash_balance": "100015068.13",
    "cash_available": "99846552.63",
    "draw_balance": "99846552.63",
    "today_profit": "200.00",
    "accu_profit": "10000.00",
    "fund_name": "现金宝",
    "fund_code": "970172",
    "frozen_funds_total": "168415.50",
    "frozen_funds_detail": [
      { "name": "stockFreeze", "value": "168415.50", "chineseDesc": "股票交易冻结" }
    ],
    "in_transit_asset_total": null
  }
}
```

---

## 3. 持仓列表 `holdings_list_card`

通过 `asset_class` 字段区分三种持仓类型，顶层结构相同：

```json
{
  "template": "holdings_list_card",
  "asset_class": "ETF | HKSC | Fund",
  "data": {
    "template": "holdings_list_card",
    "holdings": [ ... ],
    "summary": { ... }
  }
}
```

> 无账户类型区分，普通账户和两融账户共用同一格式。

### 3.1 ETF 持仓（`asset_class: "ETF"`）

**`summary` 字段：**

| 字段 | 类型 | 原始 API 路径 | 说明 |
|---|---|---|---|
| `total_market_value` | number | `results.dayTotalMktVal` | ETF 总市值 |
| `total_profit` | string | `results.dayTotalPft` | 今日总收益 |
| `total_profit_rate` | number | `results.dayTotalPftRate` | 今日总收益率（小数）|
| `total` | number | `results.total` | 持仓数量 |

**`holdings` 列表项字段：**

| 字段 | 类型 | 原始 API 字段 | 说明 |
|---|---|---|---|
| `code` | string | `secuCode` | 证券代码 |
| `name` | string | `secuName` | 证券名称 |
| `hold_cnt` | string | `holdCnt` | 持仓数量 |
| `market_value` | string | `mktVal` | 市值 |
| `day_profit` | string | `dayPft` | 今日收益 |
| `day_profit_rate` | string | `dayPftRate` | 今日收益率（小数）|
| `price` | string | `price` | 最新价 |
| `cost_price` | string | `costPrice` | 成本价 |
| `market_type` | string | `marketType` | 市场类型（`SZ`/`SH`）|
| `hold_position_profit` | string | `holdPositionPft` | 持仓盈亏 |
| `hold_position_profit_rate` | string | `holdPositionPftRate` | 持仓盈亏率 |

ETF 完整示例（Mock）：

```json
{
  "template": "holdings_list_card",
  "asset_class": "ETF",
  "data": {
    "template": "holdings_list_card",
    "holdings": [
      {
        "code": "159958",
        "name": "创业板ETF工银",
        "hold_cnt": "100",
        "market_value": "191.80",
        "day_profit": "-8.80",
        "day_profit_rate": "-0.0439",
        "price": "1.918",
        "cost_price": "1.8850",
        "market_type": "SZ",
        "hold_position_profit": "3.30",
        "hold_position_profit_rate": "0.0175"
      }
    ],
    "summary": {
      "total_market_value": 514.90,
      "total_profit": "-27.80",
      "total_profit_rate": -0.0512,
      "total": 3
    }
  }
}
```

### 3.2 港股通持仓（`asset_class: "HKSC"`）

港股通在 `summary` 中额外包含额度和预冻结信息，`data` 中额外包含 `pre_frozen_list`。

**`summary` 额外字段：**

| 字段 | 类型 | 原始 API 路径 | 说明 |
|---|---|---|---|
| `total_market_value` | number | `results.holdMktVal` | 持仓总市值 |
| `total_profit` | number | `results.dayTotalPft` | 今日总收益 |
| `total_profit_rate` | number | `results.dayTotalPftRate` | 今日总收益率 |
| `available_hksc_share` | number | `results.availableHkscShare` | 港股通可用额度（万元）|
| `limit_hksc_share` | number | `results.limitHkscShare` | 港股通限额 |
| `total_hksc_share` | number | `results.totalHkscShare` | 港股通总额度 |
| `pre_frozen_asset` | number | `results.preFrozenAsset` | 预冻结资产总额 |

**`holdings` 列表项额外字段（相比 ETF）：**

| 字段 | 类型 | 原始 API 字段 | 说明 |
|---|---|---|---|
| `share_bln` | string | `shareBln` | 可用份额 |
| `secu_acc` | string | `secuAcc` | 证券账户 |

**`pre_frozen_list` 预冻结列表项：**

| 字段 | 类型 | 原始 API 字段 | 说明 |
|---|---|---|---|
| `name` | string | `secuName` | 证券名称 |
| `code` | string | `secuCode` | 证券代码 |
| `pre_frozen_asset` | number | `preFrozenAsset` | 预冻结金额 |

港股通完整示例（Mock）：

```json
{
  "template": "holdings_list_card",
  "asset_class": "HKSC",
  "data": {
    "template": "holdings_list_card",
    "holdings": [
      {
        "code": "00700",
        "name": "腾讯控股",
        "hold_cnt": "1000",
        "market_value": 500000.00,
        "day_profit": 50.55,
        "day_profit_rate": 0.0522,
        "price": "500.00",
        "cost_price": "499.50",
        "market_type": "HK",
        "share_bln": "500",
        "hold_position_profit": 500.11,
        "hold_position_profit_rate": 0.011,
        "secu_acc": "E022922565"
      }
    ],
    "summary": {
      "total_market_value": 1000500.33,
      "total_profit": 100,
      "total_profit_rate": 0.03,
      "available_hksc_share": 6000,
      "limit_hksc_share": 4000,
      "total_hksc_share": 10000,
      "pre_frozen_asset": 6000.22
    },
    "pre_frozen_list": [
      { "name": "阿里巴巴-SW", "code": "09988", "pre_frozen_asset": 6000.22 }
    ]
  }
}
```

### 3.3 基金持仓（`asset_class: "Fund"`）

基金使用旧格式（`holdings + summary`），字段名与 ETF/港股通不同（驼峰式，来自 `FundHoldingsSchema`）。

**`summary` 字段：**

| 字段 | 类型 | 原始 API 字段 | 说明 |
|---|---|---|---|
| `total_market_value` | string | `totalMarketValue` | 总市值 |
| `total_cost` | string | `totalCost` | 总成本 |
| `total_profit` | string | `totalProfit` | 总盈亏 |
| `total_profit_rate` | string | `totalProfitRate` | 总盈亏率 |
| `today_profit` | string | `todayProfit` | 今日盈亏 |

**`holdings` 列表项字段：**

| 字段 | 类型 | 原始 API 字段 | 说明 |
|---|---|---|---|
| `product_code` | string | `productCode` | 产品代码 |
| `product_name` | string | `productName` | 产品名称 |
| `quantity` | string | `quantity` | 持有份额 |
| `cost_price` | string | `costPrice` | 成本净值 |
| `current_value` | string | `currentValue` | 当前净值 |
| `market_value` | string | `marketValue` | 市值 |
| `profit` | string | `profit` | 盈亏金额 |
| `profit_rate` | string | `profitRate` | 盈亏比率 |
| `today_profit` | string | `todayProfit` | 今日盈亏 |

基金完整示例（Mock）：

```json
{
  "template": "holdings_list_card",
  "asset_class": "Fund",
  "data": {
    "template": "holdings_list_card",
    "holdings": [
      {
        "product_code": "161725",
        "product_name": "招商中证白酒指数基金",
        "quantity": "5000",
        "cost_price": "1.2",
        "current_value": "1.35",
        "market_value": "6750.0",
        "profit": "750.0",
        "profit_rate": "0.125",
        "today_profit": "50.0"
      }
    ],
    "summary": {
      "total_market_value": "6750.0",
      "total_cost": "6000.0",
      "total_profit": "750.0",
      "total_profit_rate": "0.125",
      "today_profit": "50.0"
    }
  }
}
```

---

## 4. 单标的详情 `security_detail_card`

> 无账户类型区分。

**`holding` 持仓字段：**

| 字段 | 类型 | 原始 API 字段 | 说明 |
|---|---|---|---|
| `quantity` | string | `quantity` | 持仓数量 |
| `availableQuantity` | string | `availableQuantity` | 可用数量 |
| `costPrice` | string | `costPrice` | 成本价 |
| `currentPrice` | string | `currentPrice` | 当前价 |
| `marketValue` | string | `marketValue` | 市值 |
| `profit` | string | `profit` | 盈亏金额 |
| `profitRate` | string | `profitRate` | 盈亏比率 |
| `todayProfit` | string | `todayProfit` | 今日盈亏 |
| `todayProfitRate` | string | `todayProfitRate` | 今日盈亏比率 |

**`market_info` 行情字段：**

| 字段 | 类型 | 原始 API 字段 | 说明 |
|---|---|---|---|
| `openPrice` | string | `openPrice` | 开盘价 |
| `highPrice` | string | `highPrice` | 最高价 |
| `lowPrice` | string | `lowPrice` | 最低价 |
| `volume` | string | `volume` | 成交量 |
| `turnover` | string | `turnover` | 成交额 |
| `changeRate` | string | `changeRate` | 涨跌幅（小数）|

完整示例（Mock）：

```json
{
  "template": "security_detail_card",
  "data": {
    "template": "security_detail_card",
    "security_code": "510300",
    "security_name": "沪深300ETF",
    "security_type": "ETF",
    "market": "SH",
    "holding": {
      "quantity": "10000",
      "availableQuantity": "10000",
      "costPrice": "4.5",
      "currentPrice": "4.8",
      "marketValue": "48000.0",
      "profit": "3000.0",
      "profitRate": "0.0667",
      "todayProfit": "500.0",
      "todayProfitRate": "0.0104"
    },
    "market_info": {
      "openPrice": "4.75",
      "highPrice": "4.85",
      "lowPrice": "4.72",
      "volume": "125000000",
      "turnover": "598750000.0",
      "changeRate": "0.0106"
    }
  }
}
```

---

## 5. 开户营业部 `branch_info_card`

> 无账户类型区分。`resData` 整体透传原始 `results` 对象，所有原始字段均保留。

**`resData` 字段：**

| 字段 | 类型 | 原始 API 字段 | 说明 |
|---|---|---|---|
| `branchName` | string | `results.branchName` | 营业部全称 |
| `address` | string | `results.address` | 营业部地址 |
| `servicePhone` | string | `results.servicePhone` | 服务电话（已去除 `"营业部联系电话: "` 前缀）|
| `seatNo.sza` | string | `results.seatNo.sza` | 深交所席位号 |
| `seatNo.sha` | string | `results.seatNo.sha` | 上交所席位号 |

完整示例（Mock）：

```json
{
  "template": "branch_info_card",
  "data": {
    "template": "branch_info_card",
    "title": "资金账号：331****2926的开户营业部信息",
    "resData": {
      "branchName": "平安证券股份有限公司深圳红岭基金产业园证券营业部",
      "address": "深圳市罗湖笋岗梨园路 8号HALO广场4层, 邮编: 518000",
      "servicePhone": "95547-8-9-2",
      "seatNo": {
        "sza": "007057",
        "sha": "43599"
      }
    }
  }
}
```

---

## 附录：账户类型区分汇总

| 接口 | 普通账户 | 两融账户 | 区分方式 |
|---|---|---|---|
| `account_overview_card` | 无 `rzrqAssetsInfo` | 含 `rzrqAssetsInfo` | `data.account_type` |
| `cash_assets_card` | `cashBalance: "50000.00"` 量级 | `cashBalance: "100015068.13"` 量级 | `results.accountType` (`"1"` / `"2"`) |
| `holdings_list_card` | — | — | 无区分，共用 |
| `security_detail_card` | — | — | 无区分 |
| `branch_info_card` | — | — | 无区分 |

---

## 附录：关键源文件

| 文件 | 职责 |
|---|---|
| [`tools/field_extraction.py`](../src/ark_agentic/agents/securities/tools/field_extraction.py) | 字段路径映射与数据提取 |
| [`template_renderer.py`](../src/ark_agentic/agents/securities/template_renderer.py) | 组装最终 JSON 模板 |
| [`tools/display_card.py`](../src/ark_agentic/agents/securities/tools/display_card.py) | 账号脱敏、title 构造 |
| [`mock_data/account_overview/normal_user.json`](../src/ark_agentic/agents/securities/mock_data/account_overview/normal_user.json) | 普通账户总览 Mock |
| [`mock_data/account_overview/margin_user.json`](../src/ark_agentic/agents/securities/mock_data/account_overview/margin_user.json) | 两融账户总览 Mock |
| [`mock_data/cash_assets/normal_user.json`](../src/ark_agentic/agents/securities/mock_data/cash_assets/normal_user.json) | 普通账户现金资产 Mock（生效）|
| [`mock_data/cash_assets/margin_user.json`](../src/ark_agentic/agents/securities/mock_data/cash_assets/margin_user.json) | 两融账户现金资产 Mock（生效）|
| [`mock_data/cash_assets/default.json`](../src/ark_agentic/agents/securities/mock_data/cash_assets/default.json) | 旧格式，已废弃 |
