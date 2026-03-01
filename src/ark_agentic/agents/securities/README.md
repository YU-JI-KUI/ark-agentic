# 证券资产管理 Agent

证券资产管理智能体，支持普通账户和两融账户的资产查询、持仓分析、收益统计等功能。

## 快速开始

### 环境变量

```bash
# LLM 配置（必选其一）
LLM_PROVIDER=pa                    # pa / deepseek / openai / mock
PA_MODEL=PA-SX-80B                 # PA 模型（PA-JT-80B / PA-SX-80B / PA-SX-235B）
DEEPSEEK_API_KEY=sk-xxx            # DeepSeek 模式时需要

# 证券服务配置
SECURITIES_SERVICE_MOCK=true       # 启用 Mock 模式（开发/测试用）
SECURITIES_ACCOUNT_TYPE=normal     # 默认账户类型：normal / margin

# 可选
SESSIONS_DIR=./sessions            # 会话持久化目录
LOG_LEVEL=INFO                     # 日志级别
API_HOST=0.0.0.0                   # API 监听地址
API_PORT=8080                      # API 监听端口
```

### 启动服务

```bash
# 安装依赖
uv sync

# 启动（Mock 模式）
SECURITIES_SERVICE_MOCK=true uv run python -m ark_agentic.app

# 访问
# API: http://localhost:8080/docs
# 测试 UI: http://localhost:8080/
```

---

## API 接口说明（前端对接）

### HTTP 端点

| 端点 | 方法 | 描述 |
|------|------|------|
| `/chat` | POST | 发送消息（支持流式/非流式） |
| `/sessions` | POST | 创建新会话 |
| `/sessions/{session_id}` | GET | 获取会话历史 |
| `/sessions/{session_id}` | DELETE | 删除会话 |
| `/sessions` | GET | 列出所有会话 |
| `/health` | GET | 健康检查 |

### Chat 请求

**端点:** `POST /chat`

**请求体:**

```json
{
  "agent_id": "securities",
  "message": "查询我的账户总资产",
  "session_id": null,
  "stream": true,
  "user_id": "U001",
  "context": {
    "user_id": "U001",
    "token_id": "N_4ABD52CE290DD385...",
    "account_type": "normal"
  }
}
```

**请求字段说明:**

| 字段 | 类型 | 必填 | 描述 |
|------|------|------|------|
| `agent_id` | string | 是 | Agent ID，固定为 `"securities"` |
| `message` | string | 是 | 用户消息内容 |
| `session_id` | string | 否 | 会话 ID，为空则创建新会话 |
| `stream` | boolean | 否 | 是否启用 SSE 流式输出，默认 `false` |
| `user_id` | string | 否 | 用户 ID |
| `context` | object | 否 | 业务上下文数据 |

**Context 字段说明:**

| 字段 | 类型 | 必填 | 描述 |
|------|------|------|------|
| `user_id` | string | 否 | 用户 ID |
| `token_id` | string | 是* | 登录令牌（调用真实 API 必需） |
| `account_type` | string | 否 | 账户类型：`"normal"` 或 `"margin"`，默认 `"normal"` |

> *`token_id` 在 Mock 模式下可选，生产环境必需。

### Chat 响应（非流式）

```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "response": "您的账户总资产为 1,000,000.00 元...",
  "tool_calls": [
    {"name": "account_overview", "arguments": {}},
    {"name": "display_card", "arguments": {"source_tool": "account_overview"}}
  ],
  "turns": 1,
  "usage": {
    "prompt_tokens": 150,
    "completion_tokens": 80
  }
}
```

### SSE 流式事件（流式模式）

当 `stream: true` 时，响应为 `text/event-stream` 格式。

**事件类型:**

| 事件类型 | 描述 |
|----------|------|
| `response.created` | Run 初始化 |
| `response.step` | Agent 执行步骤（工具调用等） |
| `response.content.delta` | 最终回答文本片段（打字机效果） |
| `response.ui.component` | JSON 模板卡片数据（A2UI 组件） |
| `response.completed` | Run 完成 |
| `response.failed` | 错误 |

#### response.created

```json
{
  "type": "response.created",
  "seq": 1,
  "run_id": "run_abc123",
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "content": "收到您的消息，正在处理中…"
}
```

#### response.step

```json
{
  "type": "response.step",
  "seq": 2,
  "run_id": "run_abc123",
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "content": "调用工具 account_overview 查询账户总资产"
}
```

#### response.content.delta

```json
{
  "type": "response.content.delta",
  "seq": 5,
  "run_id": "run_abc123",
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "delta": "您的账户总资产为",
  "output_index": 0
}
```

#### response.ui.component

前端收到此事件后，根据 `ui_component.template_type` 渲染对应的卡片组件。

```json
{
  "type": "response.ui.component",
  "seq": 4,
  "run_id": "run_abc123",
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "ui_component": {
    "template_type": "account_overview_card",
    "data": {
      "total_assets": "1000000.00",
      "cash_balance": "500000.00",
      "stock_market_value": "500000.00",
      "today_profit": "5000.00",
      "account_type": "normal"
    }
  }
}
```

#### response.completed

```json
{
  "type": "response.completed",
  "seq": 6,
  "run_id": "run_abc123",
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "message": "您的账户总资产为 1,000,000.00 元...",
  "tool_calls": [...],
  "turns": 1,
  "usage": {
    "prompt_tokens": 150,
    "completion_tokens": 80
  }
}
```

#### response.failed

```json
{
  "type": "response.failed",
  "seq": 3,
  "run_id": "run_abc123",
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "error_message": "API returned error: Invalid token"
}
```

---

## 模板卡片类型

前端收到 `response.ui.component` 事件后，根据 `template_type` 渲染对应的卡片组件。

### account_overview_card（账户总览卡片）

```json
{
  "template_type": "account_overview_card",
  "data": {
    "total_assets": "1000000.00",
    "cash_balance": "500000.00",
    "stock_market_value": "400000.00",
    "fund_market_value": "100000.00",
    "today_profit": "5000.00",
    "today_return_rate": "0.0050",
    "account_type": "normal",
    "net_assets": null,
    "total_liabilities": null,
    "maintenance_margin_ratio": null
  }
}
```

**字段说明:**

| 字段 | 类型 | 描述 | 适用账户 |
|------|------|------|----------|
| `total_assets` | string | 总资产 | 全部 |
| `cash_balance` | string | 现金余额 | 全部 |
| `stock_market_value` | string | 股票市值 | 全部 |
| `fund_market_value` | string | 基金市值 | 普通账户 |
| `today_profit` | string | 今日收益 | 全部 |
| `today_return_rate` | string | 今日收益率 | 全部 |
| `account_type` | string | 账户类型：`normal` / `margin` | 全部 |
| `net_assets` | string | 净资产 | 两融账户 |
| `total_liabilities` | string | 总负债 | 两融账户 |
| `maintenance_margin_ratio` | string | 维持担保比例 | 两融账户 |

### cash_assets_card（现金资产卡片）

```json
{
  "template_type": "cash_assets_card",
  "data": {
    "cash_balance": "500000.00",
    "cash_available": "450000.00",
    "draw_balance": "400000.00",
    "today_profit": "100.00",
    "accu_profit": "5000.00",
    "fund_name": "天天利",
    "fund_code": "001234",
    "frozen_funds_total": "50000.00",
    "frozen_funds_detail": [...],
    "in_transit_asset_total": "10000.00"
  }
}
```

**字段说明:**

| 字段 | 类型 | 描述 |
|------|------|------|
| `cash_balance` | string | 现金总额 |
| `cash_available` | string | 可用资金 |
| `draw_balance` | string | 可取资金 |
| `today_profit` | string | 今日收益 |
| `accu_profit` | string | 累计收益 |
| `fund_name` | string | 理财产品名称 |
| `fund_code` | string | 理财产品代码 |
| `frozen_funds_total` | string | 冻结资金总额 |
| `frozen_funds_detail` | array | 冻结资金明细 |
| `in_transit_asset_total` | string | 在途资产总额 |

### holdings_list_card（持仓列表卡片）

用于 ETF、港股通、基金持仓列表。

```json
{
  "template_type": "holdings_list_card",
  "asset_class": "ETF",
  "data": {
    "holdings": [
      {
        "code": "510300",
        "name": "沪深300ETF",
        "hold_cnt": "1000",
        "market_value": "4500000.00",
        "day_profit": "5000.00",
        "day_profit_rate": "0.0011",
        "price": "4.500",
        "cost_price": "4.200",
        "hold_position_profit": "30000.00",
        "hold_position_profit_rate": "0.0667"
      }
    ],
    "summary": {
      "total_market_value": "4500000.00",
      "total_profit": "5000.00",
      "total_profit_rate": "0.0011",
      "total": 1
    }
  }
}
```

**asset_class 取值:**

| 值 | 描述 |
|----|------|
| `ETF` | ETF 持仓 |
| `HKSC` | 港股通持仓 |
| `Fund` | 基金持仓 |

**持仓项字段（holdings[]）:**

| 字段 | 类型 | 描述 |
|------|------|------|
| `code` | string | 证券代码 |
| `name` | string | 证券名称 |
| `hold_cnt` | string | 持仓数量 |
| `market_value` | string | 市值 |
| `day_profit` | string | 今日收益 |
| `day_profit_rate` | string | 今日收益率 |
| `price` | string | 当前价格 |
| `cost_price` | string | 成本价 |
| `hold_position_profit` | string | 持仓盈亏 |
| `hold_position_profit_rate` | string | 持仓盈亏率 |

**港股通特有字段:**

| 字段 | 类型 | 描述 |
|------|------|------|
| `share_bln` | string | 可用份额 |
| `position` | string | 持仓位置 |
| `secu_acc` | string | 证券账户 |

**汇总字段（summary）:**

| 字段 | 类型 | 描述 |
|------|------|------|
| `total_market_value` | string | 总市值 |
| `total_profit` | string | 今日总收益 |
| `total_profit_rate` | string | 今日收益率 |
| `total` | number | 持仓数量 |

**港股通特有汇总字段:**

| 字段 | 类型 | 描述 |
|------|------|------|
| `available_hksc_share` | string | 港股通可用额度 |
| `limit_hksc_share` | string | 港股通限额 |
| `total_hksc_share` | string | 港股通总额度 |
| `pre_frozen_asset` | string | 预冻结资产 |

### security_detail_card（标的详情卡片）

```json
{
  "template_type": "security_detail_card",
  "data": {
    "security_code": "510300",
    "security_name": "沪深300ETF",
    "security_type": "ETF",
    "market": "SH",
    "holding": {
      "quantity": "1000",
      "available_quantity": "1000",
      "cost_price": "4.200",
      "current_price": "4.500",
      "market_value": "4500.00",
      "profit": "300.00",
      "profit_rate": "0.0714",
      "today_profit": "50.00",
      "today_profit_rate": "0.0111"
    },
    "market_info": {
      "open_price": "4.480",
      "high_price": "4.520",
      "low_price": "4.460",
      "volume": "12345678",
      "turnover": "55555555.00",
      "change_rate": "0.0111"
    }
  }
}
```

---

## 前端集成示例

### JavaScript (Fetch API)

```javascript
// 发送消息（流式）
async function sendMessage(message, context) {
  const payload = {
    message: message,
    agent_id: "securities",
    stream: true,
    user_id: context.user_id,
    context: {
      user_id: context.user_id,
      token_id: context.token_id,
      account_type: context.account_type || "normal"
    }
  };

  const resp = await fetch('/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    const lines = buffer.split('\n');
    buffer = lines.pop();

    for (const line of lines) {
      if (line.startsWith('data:')) {
        const event = JSON.parse(line.slice(5).trim());
        handleSSEEvent(event);
      }
    }
  }
}

// 处理 SSE 事件
function handleSSEEvent(event) {
  switch (event.type) {
    case 'response.ui.component':
      renderTemplateCard(event.ui_component);
      break;
    case 'response.content.delta':
      appendText(event.delta);
      break;
    case 'response.completed':
      finalizeResponse(event);
      break;
    case 'response.failed':
      showError(event.error_message);
      break;
  }
}

// 渲染模板卡片
function renderTemplateCard(template) {
  switch (template.template_type) {
    case 'account_overview_card':
      renderAccountOverview(template.data);
      break;
    case 'holdings_list_card':
      renderHoldingsList(template.asset_class, template.data);
      break;
    case 'cash_assets_card':
      renderCashAssets(template.data);
      break;
    case 'security_detail_card':
      renderSecurityDetail(template.data);
      break;
  }
}
```

---

## 架构概览

```
agents/securities/
├── agent.py              # Agent 创建 & Prompt 定义
├── api.py                # 环境变量加载 & 工厂函数
├── schemas.py            # Pydantic 数据模型（str 精度）
├── template_renderer.py  # JSON 卡片渲染器
├── tools/
│   ├── __init__.py       # 工具注册
│   ├── service_client.py # 服务适配器层（6 个 Adapter + Mock + 工厂）
│   ├── mock_loader.py    # 文件驱动 Mock 数据加载
│   ├── param_mapping.py  # API 参数映射工具
│   ├── field_extraction.py # API 响应字段提取工具
│   ├── display_card.py   # 卡片渲染工具（字段提取 + 模板渲染）
│   ├── account_overview.py
│   ├── cash_assets.py
│   ├── etf_holdings.py
│   ├── hksc_holdings.py
│   ├── fund_holdings.py
│   └── security_detail.py
├── mock_data/            # Mock 数据文件（JSON，真实 API 格式）
│   ├── account_overview/
│   ├── cash_assets/
│   ├── etf_holdings/
│   ├── fund_holdings/
│   ├── hksc_holdings/
│   └── security_detail/
├── skills/               # 技能定义
│   ├── asset_overview/SKILL.md
│   ├── holdings_analysis/SKILL.md
│   └── profit_inquiry/SKILL.md
└── templates/            # 预留模板目录
```

## 工具清单

| 工具名 | 描述 | 参数 |
|--------|------|------|
| `account_overview` | 查询账户总资产 | `account_type?` |
| `cash_assets` | 查询现金资产 | `account_type?` |
| `etf_holdings` | 查询 ETF 持仓 | `account_type?` |
| `hksc_holdings` | 查询港股通持仓 | `account_type?` |
| `fund_holdings` | 查询基金理财持仓 | `account_type?` |
| `security_detail` | 查询具体标的详情 | `security_code`, `account_type?` |
| `display_card` | 渲染数据卡片 | `source_tool` |

> **注意：** `account_type` 由系统自动从 Session Context 注入，LLM 无需显式传递。

## 数据流程

```
┌─────────────────────────────────────────────────────────────────────┐
│                         完整数据流程                                 │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  1. 参数获取（扁平 context）                                          │
│     context.token_id ────────┐                                       │
│     context.account_type ────┼──► param_mapping.build_api_request    │
│     static config ───────────┘       │                               │
│                                      ▼                               │
│  2. API 调用                     {channel, appName, tokenId, body}   │
│     service_client.call() ───────► 真实 API / Mock 数据              │
│                                    │                                 │
│                                    ▼                                 │
│  3. 原始响应                     {status, results: {rmb: {...}}}     │
│     account_overview 返回 ───────► 原始 API 格式数据                  │
│                                    │                                 │
│                                    ▼                                 │
│  4. 字段提取                     field_extraction.extract_xxx()      │
│     display_card 调用 ──────────► 提取显示字段 {total_assets, ...}   │
│                                    │                                 │
│                                    ▼                                 │
│  5. 模板渲染                     template_renderer.render_xxx_card() │
│     display_card 返回 ──────────► {template_type, data}             │
│                                    │                                 │
│                                    ▼                                 │
│  6. SSE 推送                     response.ui.component 事件         │
│     app.py 直发 ────────────────► 前端渲染卡片                       │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

## 参数映射设计

### 配置结构

参数映射使用配置字典定义 API 请求体的构建方式：

```python
# param_mapping.py
# context 为扁平结构: {"token_id": "xxx", "account_type": "normal", "user_id": "U001"}
ACCOUNT_OVERVIEW_PARAM_CONFIG = {
    # "API字段": ("来源类型", 来源值, [转换函数])
    "channel": ("static", "native"),
    "appName": ("static", "AYLCAPP"),
    "tokenId": ("context", "token_id"),           # 从扁平 context 获取
    "body.accountType": ("transform", "account_type",  # 从扁平 context 获取
                         lambda x: "2" if x == "margin" else "1"),
}
```

### 来源类型

| 类型 | 说明 | 示例 |
|------|------|------|
| `static` | 固定值 | `("static", "native")` |
| `context` | 从扁平 context 获取 | `("context", "token_id")` |
| `transform` | 获取后转换 | `("transform", "account_type", fn)` |

### 使用方式

```python
from ark_agentic.agents.securities.tools.param_mapping import (
    build_api_request, SERVICE_PARAM_CONFIGS
)

# 扁平 context 结构
context = {"token_id": "xxx", "account_type": "margin", "user_id": "U001"}
config = SERVICE_PARAM_CONFIGS["account_overview"]
request_body = build_api_request(config, context)
# {"channel": "native", "appName": "AYLCAPP", "tokenId": "xxx",
#  "body": {"accountType": "2"}}
```

## 字段提取设计

### 配置结构

字段提取使用点号路径映射 API 响应字段到显示字段：

```python
# field_extraction.py
ACCOUNT_OVERVIEW_FIELD_MAPPING = {
    # "显示字段名": "API响应路径"
    "total_assets": "results.rmb.totalAssetVal",
    "cash_balance": "results.rmb.cashGainAssetsInfo.cashBalance",
    "stock_market_value": "results.rmb.mktAssetsInfo.totalMktVal",
    "fund_market_value": "results.rmb.fundMktAssetsInfo.fundMktVal",
    "today_profit": "results.rmb.mktAssetsInfo.totalMktProfitToday",
    "today_return_rate": "results.rmb.mktAssetsInfo.totalMktYieldToday",
    # 两融账户特有字段
    "net_assets": "results.rmb.rzrqAssetsInfo.netWorth",
    "total_liabilities": "results.rmb.rzrqAssetsInfo.totalLiabilities",
    "maintenance_margin_ratio": "results.rmb.rzrqAssetsInfo.mainRatio",
}
```

### 使用方式

```python
from ark_agentic.agents.securities.tools.field_extraction import (
    extract_account_overview
)

# 从 API 响应提取显示字段
api_response = {"status": 1, "results": {"rmb": {...}}}
display_data = extract_account_overview(api_response)
# {"total_assets": "1000000.00", "cash_balance": "500000.00", ...}
```

## 账户类型差异化

| 特性 | 普通账户 (normal) | 两融账户 (margin) |
|------|-------------------|-------------------|
| 基础字段 | ✅ 总资产、现金、股票市值、收益 | ✅ 同左 |
| 基金市值 | ✅ `fund_market_value` | — (通常为 null) |
| 今日收益率 | ✅ `today_return_rate` | ✅ `today_return_rate` |
| 净资产 | — | ✅ `net_assets` |
| 总负债 | — | ✅ `total_liabilities` |
| 维持担保比例 | — | ✅ `maintenance_margin_ratio` |

**优先级链：** `args.account_type → context.account_type → "normal"`

## 测试

```bash
# 运行参数映射和字段提取单元测试
uv run pytest tests/agents/securities/ -v

# 运行集成测试
SECURITIES_SERVICE_MOCK=true uv run pytest tests/test_context_injection.py tests/test_skills_integration.py -v

# 运行所有证券相关测试
SECURITIES_SERVICE_MOCK=true uv run pytest tests/ -v -k "securities or context_injection or skills_integration"
```

## 设计决策

1. **String 精度** — 所有金融数据字段使用 `str` 类型，避免浮点精度丢失
2. **Context 注入** — 工具层自动从 Session Context 获取 `account_type`，减轻 LLM 负担
3. **结构化模板** — 模板通过工具 metadata 传递，不依赖 LLM 文本输出
4. **适配器模式** — 每个服务一个 Adapter 子类，新增服务只需 3 步（Schema + Adapter + 注册）
5. **配置驱动** — 参数映射和字段提取均通过配置字典管理，易于扩展新服务
6. **关注点分离** — 数据工具返回原始数据，display_card 负责字段提取和模板渲染
7. **SSE 直推** — 模板数据通过 `response.ui.component` 事件直推前端，无需解析 LLM 文本

## 扩展新服务

添加新服务的步骤：

1. **定义字段映射** (`field_extraction.py`)
```python
NEW_SERVICE_FIELD_MAPPING = {
    "display_field": "api.path.to.field",
}
```

2. **定义参数映射** (`param_mapping.py`)
```python
NEW_SERVICE_PARAM_CONFIG = {
    "api_field": ("source_type", source_value),
}
SERVICE_PARAM_CONFIGS["new_service"] = NEW_SERVICE_PARAM_CONFIG
```

3. **创建 Adapter** (`service_client.py`)
```python
class NewServiceAdapter(BaseServiceAdapter):
    def _normalize_response(self, raw_data, account_type):
        return raw_data  # 返回原始数据，由 display_card 处理
```

4. **注册到工厂函数** (`service_client.py`)
```python
adapter_map["new_service"] = NewServiceAdapter
```

5. **添加 Mock 数据** (`mock_data/new_service/default.json`)
