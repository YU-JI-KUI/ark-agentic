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
│   ├── account_overview.py
│   ├── cash_assets.py
│   ├── etf_holdings.py
│   ├── hksc_holdings.py
│   ├── fund_holdings.py
│   └── security_detail.py
├── mock_data/            # Mock 数据文件（JSON）
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

> **注意：** `account_type` 由系统自动从 Session 上下文注入，LLM 无需显式传递。

## 账户类型差异化

| 特性 | 普通账户 (normal) | 两融账户 (margin) |
|------|-------------------|-------------------|
| 基础字段 | ✅ 总资产、现金、股票市值、收益 | ✅ 同左 |
| 维持担保比率 | — | ✅ `margin_ratio` |
| 风险等级 | — | ✅ `risk_level` (low/medium/high) |
| 维持保证金 | — | ✅ `maintenance_margin` |
| 可用保证金 | — | ✅ `available_margin` |

**优先级链：** `args.account_type → context.account_type → "normal"`

## SSE 模板协议

工具执行后，模板卡片通过 `metadata.template` 自动携带，由 `app.py` 直发 SSE 事件：

```
Tool 返回 data + metadata.template → RunResult.tool_results
→ app.py 遍历 tool_results → SSE event: response.template
```

前端收到 `response.template` 事件后直接渲染卡片，无需解析 LLM 文本。

## 测试

```bash
# 运行所有证券相关测试
SECURITIES_SERVICE_MOCK=true uv run pytest tests/test_context_injection.py tests/test_schema_str_coercion.py tests/test_skills_integration.py -v
```

## 设计决策

1. **String 精度** — 所有金融数据字段使用 `str` 类型，避免浮点精度丢失
2. **Context 注入** — 工具层自动从 Session Context 获取 `account_type`，减轻 LLM 负担
3. **结构化模板** — 模板通过工具 metadata 传递，不依赖 LLM 文本输出
4. **适配器模式** — 每个服务一个 Adapter 子类，新增服务只需 3 步（Schema + Adapter + 注册）
