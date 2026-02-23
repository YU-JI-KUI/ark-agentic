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
│   ├── param_mapping.py  # API 参数映射工具（新增）
│   ├── field_extraction.py # API 响应字段提取工具（新增）
│   ├── display_card.py   # 卡片渲染工具（字段提取 + 模板渲染）
│   ├── account_overview.py
│   ├── cash_assets.py
│   ├── etf_holdings.py
│   ├── hksc_holdings.py
│   ├── fund_holdings.py
│   └── security_detail.py
├── mock_data/            # Mock 数据文件（JSON，真实 API 格式）
│   ├── account_overview/ # normal_user.json, margin_user.json
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

### 双格式兼容

系统自动检测响应格式，支持真实 API 格式和旧格式：

```python
# 真实 API 格式
{"status": 1, "results": {"rmb": {"totalAssetVal": "1000000.00", ...}}}

# 旧格式（向后兼容）
{"data": {"totalAssets": "1000000.00", ...}}
```

### 使用方式

```python
from ark_agentic.agents.securities.tools.field_extraction import (
    extract_account_overview
)

# 自动检测格式并提取字段
api_response = {"status": 1, "results": {"rmb": {...}}}
display_data = extract_account_overview(api_response)
# {"total_assets": "1000000.00", "cash_balance": "500000.00", ...}
```

## Context 结构

### 扁平结构设计

Context 使用扁平结构，所有业务参数都在顶层：

```json
{
  "user_id": "U001",
  "token_id": "N_4ABD52CE290DD385...",
  "account_type": "normal"
}
```

### 字段说明

| 字段 | 类型 | 来源 | 说明 |
|------|------|------|------|
| `user_id` | string | 前端/后端 | 用户 ID |
| `token_id` | string | 前端 | 登录令牌（调用真实 API 必需） |
| `account_type` | string | 前端 | 账户类型：normal/margin |

### 前端传入方式

```javascript
// index.html
const payload = {
  message: text,
  agent_id: "securities",
  user_id: selectedUserId,
  context: {
    user_id: selectedUserId,
    token_id: tokenId,              // 从登录获取
    account_type: selectedAccountType  // normal 或 margin
  },
};
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

## SSE 模板协议

工具执行后，模板卡片通过 `metadata.template` 自动携带，由 `app.py` 直发 SSE 事件：

```
display_card 返回 data + metadata.template → RunResult.tool_results
→ app.py 遍历 tool_results → SSE event: response.template
```

前端收到 `response.template` 事件后直接渲染卡片，无需解析 LLM 文本。

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
6. **双格式兼容** — 自动检测 API 响应格式，向后兼容旧格式
7. **关注点分离** — 数据工具返回原始数据，display_card 负责字段提取和模板渲染

## 扩展新服务

添加新服务的步骤：

1. **定义字段映射** (`field_extraction.py`)
```python
NEW_SERVICE_FIELD_MAPPING = {
    "display_field": "api.path.to.field",
}
SERVICE_FIELD_MAPPINGS["new_service"] = {
    "real": NEW_SERVICE_FIELD_MAPPING,
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
