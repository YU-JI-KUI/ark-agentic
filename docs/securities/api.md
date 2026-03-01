# Ark-Agentic API 文档

## 概述

Ark-Agentic 提供统一的 RESTful API，支持多 Agent（insurance、securities）交互，含 SSE 流式输出。

**Base URL:** `http://localhost:8080`  
**Swagger UI:** `http://localhost:8080/docs`

---

## 端点一览

| 方法 | 路径 | 描述 |
|------|------|------|
| `POST` | `/chat` | 发送消息（支持流式/非流式） |
| `POST` | `/sessions` | 创建会话 |
| `GET` | `/sessions` | 列出所有会话 |
| `GET` | `/sessions/{session_id}` | 获取会话历史 |
| `DELETE` | `/sessions/{session_id}` | 删除会话 |
| `GET` | `/health` | 健康检查 |

---

## POST /chat

### 请求体

```json
{
  "agent_id": "securities",
  "message": "查看我的资产",
  "session_id": "可选，为空则自动创建",
  "stream": true,
  "model": null,
  "temperature": null,
  "user_id": "可选",
  "context": {
    "account_type": "margin"
  },
  "idempotency_key": null
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `agent_id` | string | 否 | Agent 标识，`insurance` 或 `securities`，默认 `insurance` |
| `message` | string | **是** | 用户消息 |
| `session_id` | string | 否 | 会话 ID，为空则创建新会话 |
| `stream` | boolean | 否 | 是否启用 SSE 流式输出，默认 `false` |
| `model` | string | 否 | 覆盖默认模型 |
| `temperature` | float | 否 | 采样温度 (0.0-2.0) |
| `user_id` | string | 否 | 用户 ID（也可通过 Header `x-ark-user-id` 传递） |
| `context` | object | 否 | 业务上下文，如 `account_type` |
| `idempotency_key` | string | 否 | 幂等键 |

### 请求 Headers（可选）

| Header | 说明 |
|--------|------|
| `x-ark-session-key` | 会话 ID（优先级低于 body） |
| `x-ark-user-id` | 用户 ID（优先级低于 body） |
| `x-ark-trace-id` | 追踪 ID |

### 非流式响应 (`stream: false`)

```json
{
  "session_id": "abc-123",
  "response": "已为您查询到账户资产信息。",
  "tool_calls": [
    {"name": "account_overview", "arguments": {}}
  ],
  "turns": 2,
  "usage": {
    "prompt_tokens": 500,
    "completion_tokens": 50
  }
}
```

### 流式响应 (`stream: true`)

返回 `text/event-stream`（SSE），事件格式如下：

```
event: response.created
data: {"type":"response.created","seq":1,"run_id":"...","session_id":"...","content":"收到您的消息，正在处理中…"}

event: response.step
data: {"type":"response.step","seq":2,"content":"正在查询账户总资产…"}

event: response.template
data: {"type":"response.template","seq":3,"template":{"template_type":"account_overview_card","data":{...}}}

event: response.content.delta
data: {"type":"response.content.delta","seq":4,"delta":"已为您","output_index":0}

event: response.content.delta
data: {"type":"response.content.delta","seq":5,"delta":"查询到资产信息。","output_index":0}

event: response.completed
data: {"type":"response.completed","seq":6,"message":"已为您查询到资产信息。","turns":2,"usage":{"prompt_tokens":500,"completion_tokens":50}}
```

---

## SSE 事件类型

| 事件类型 | 描述 | 关键字段 |
|----------|------|----------|
| `response.created` | 请求已接收，开始处理 | `content` |
| `response.step` | Agent 生命周期步骤（工具调用状态等） | `content` |
| `response.content.delta` | 最终回答文本片段（逐字输出） | `delta`, `output_index` |
| `response.template` | JSON 模板卡片（前端直接渲染） | `template` |
| `response.completed` | 执行完成 | `message`, `turns`, `usage`, `tool_calls` |
| `response.failed` | 执行失败 | `error_message` |

### response.template 详解

模板卡片由工具自动生成，通过 `metadata.template` 传递到 SSE 层。前端收到此事件后直接渲染，无需解析 LLM 文本。

#### 模板类型

| `template_type` | 描述 | 触发工具 |
|------------------|------|----------|
| `account_overview_card` | 账户资产总览卡片 | `account_overview` |
| `holdings_list_card` | 持仓列表卡片 | `etf_holdings`, `hksc_holdings`, `fund_holdings` |
| `cash_assets_card` | 现金资产卡片 | `cash_assets` |
| `security_detail_card` | 标的详情卡片 | `security_detail` |
| `profit_summary_card` | 收益汇总卡片 | — |

#### 示例：account_overview_card

```json
{
  "template_type": "account_overview_card",
  "data": {
    "total_assets": "1250000.50",
    "cash_balance": "150000.00",
    "stock_market_value": "1100000.50",
    "today_profit": "3500.25",
    "total_profit": "125000.00",
    "profit_rate": "0.11",
    "account_type": "normal",
    "margin_ratio": null,
    "risk_level": null,
    "update_time": "2024-01-15T10:30:00"
  }
}
```

#### 示例：holdings_list_card

```json
{
  "template_type": "holdings_list_card",
  "asset_class": "ETF",
  "data": {
    "holdings": [
      {
        "code": "510300",
        "name": "沪深300ETF",
        "quantity": "1000",
        "cost_price": "4.50",
        "current_price": "4.80",
        "profit": "300.00"
      }
    ],
    "summary": {}
  }
}
```

---

## POST /sessions

创建新会话。

```json
// Request
{ "agent_id": "securities", "metadata": {"user_id": "U001"} }

// Response
{ "session_id": "abc-123", "message_count": 0, "metadata": {"user_id": "U001"} }
```

## GET /sessions?agent_id=securities

列出所有会话。

```json
{
  "sessions": [
    { "session_id": "abc-123", "message_count": 5, "metadata": {} }
  ]
}
```

## GET /sessions/{session_id}?agent_id=securities

获取会话消息历史。

```json
{
  "session_id": "abc-123",
  "messages": [
    { "role": "user", "content": "查看我的资产", "tool_calls": null },
    { "role": "assistant", "content": "已为您查询到资产信息。", "tool_calls": [{"name": "account_overview", "arguments": {}}] }
  ]
}
```

## DELETE /sessions/{session_id}?agent_id=securities

```json
{ "status": "deleted", "session_id": "abc-123" }
```

---

## Securities Agent 上下文注入

对 `agent_id=securities` 的请求，系统会自动从 `context` 中提取以下字段并注入 Session：

| 字段 | 来源 | 说明 |
|------|------|------|
| `account_type` | `context.account_type` 或环境变量 `SECURITIES_ACCOUNT_TYPE` | 账户类型，仅首次设置 |
| `user_id` | `user_id` 字段或 `x-ark-user-id` Header | 用户 ID |

注入后，所有工具自动从 Session Context 读取这些值，无需 LLM 显式传递。
