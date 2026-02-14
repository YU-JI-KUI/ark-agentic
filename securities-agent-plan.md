# 证券资产管理 Agent 实现计划

> **版本**: v1.0  
> **创建日期**: 2026-02-14  
> **分支**: securities

---

## 📋 目标概述

开发证券资产管理智能体，支持：

1. **账户资产查询**：总资产、现金、股票市值、今日收益
2. **分类资产查询**：ETF、港股通、基金理财的持仓和收益
3. **具体标的查询**：单只股票/基金/ETF 的持仓与盈亏
4. **账户类型差异化**：普通账户 vs 两融账户（含维持担保比率等风险指标）
5. **多服务接口适配**：统一不同团队提供的 RESTful 接口
6. **双响应格式**：Markdown 文本 + JSON 预定义模板卡片

---

## 🎯 核心设计决策

### 1. 服务适配层架构

采用**适配器模式**统一不同服务接口：

```
BaseServiceAdapter (抽象基类)
    ├── AccountOverviewAdapter
    ├── ETFHoldingsAdapter
    ├── HKSCHoldingsAdapter
    ├── FundHoldingsAdapter
    ├── CashAssetsAdapter
    └── SecurityDetailAdapter
```

**特性**：
- 支持 Header 和 Body 两种认证方式
- 字段名称自动标准化（模糊命名 → 标准字段）
- 统一错误处理和重试机制

### 2. Mock 数据系统（文件驱动）

**设计目标**：加速本地开发，无需真实服务接口

**核心组件**：
- `MockDataLoader`：从 JSON 文件加载数据
- `MockServiceAdapter`：集成文件加载逻辑
- 场景化数据：普通账户、两融账户、高收益等

**目录结构**：
```
src/ark_agentic/agents/securities/
├── mock_data/
│   ├── account_overview/
│   │   ├── normal_user.json    # 普通账户
│   │   ├── margin_user.json    # 两融账户
│   │   └── high_profit.json    # 高收益场景
│   ├── etf_holdings/default.json
│   ├── hksc_holdings/default.json
│   ├── fund_holdings/default.json
│   ├── cash_assets/default.json
│   └── security_detail/
│       ├── stock_510300.json   # 按标的代码
│       └── fund_161725.json
```

**使用方式**：
```bash
export SECURITIES_SERVICE_MOCK=true
python -m ark_agentic.agents.securities.agent -i
```

### 3. 账户类型处理

通过 `account_type` 上下文参数动态处理：

```python
# 普通账户
context = {"account_type": "normal", "user_id": "U001"}

# 两融账户
context = {"account_type": "margin", "user_id": "U001"}
```

**差异化处理**：
- 服务接口选择（不同账户类型可能调用不同 API）
- 字段映射（两融账户返回额外风险指标）
- 响应格式（两融账户显示维持担保比率）

### 4. 响应格式

**双模式支持**：

1. **纯文本模式**（默认）：Markdown 富文本
2. **模板模式**（意图明确时）：JSON 模板 + 文本

**模板渲染流程**：
```
用户输入 → 意图识别 → 判断是否返回模板
    ├─ 是 → SSE: response.template + response.content.delta
    └─ 否 → SSE: response.content.delta
```

---

## 🏗️ 项目结构

```
src/ark_agentic/agents/securities/
├── __init__.py
├── agent.py                    # Agent 创建和配置
├── api.py                      # 环境变量加载
├── tools/                      # 工具层
│   ├── __init__.py
│   ├── mock_loader.py          # Mock 数据加载器
│   ├── service_client.py       # 服务适配层
│   ├── account_overview.py     # 账户总资产工具
│   ├── cash_assets.py          # 现金资产工具
│   ├── etf_holdings.py         # ETF 持仓工具
│   ├── hksc_holdings.py        # 港股通持仓工具
│   ├── fund_holdings.py        # 基金理财工具
│   └── security_detail.py      # 具体标的工具
├── skills/                     # 技能层
│   ├── asset_overview/
│   │   └── SKILL.md
│   ├── holdings_analysis/
│   │   └── SKILL.md
│   └── profit_inquiry/
│       └── SKILL.md
├── templates/                  # JSON 模板定义
│   ├── account_overview.json
│   ├── holdings_list.json
│   └── profit_summary.json
└── mock_data/                  # Mock 数据文件
    ├── account_overview/
    ├── etf_holdings/
    ├── hksc_holdings/
    ├── fund_holdings/
    ├── cash_assets/
    └── security_detail/
```

---

## 📦 组件详细设计

### 组件一：Mock 数据系统

#### MockDataLoader 类

```python
class MockDataLoader:
    """从 JSON 文件加载 Mock 数据"""
    
    def load(
        self,
        service_name: str,
        scenario: str = "default",
        **params: Any,
    ) -> dict[str, Any]:
        """
        加载逻辑：
        1. 优先查找参数特定文件（如 stock_510300.json）
        2. 其次查找场景文件（如 margin_user.json）
        3. 最后查找默认文件（default.json）
        """
```

#### Mock 数据文件示例

**account_overview/normal_user.json**：
```json
{
  "code": 0,
  "message": "success",
  "data": {
    "totalAssets": 1250000.00,
    "cashBalance": 50000.00,
    "stockValue": 1200000.00,
    "todayProfit": 15000.00,
    "totalProfit": 250000.00,
    "profitRate": 0.25
  }
}
```

**account_overview/margin_user.json**（两融账户）：
```json
{
  "code": 0,
  "message": "success",
  "data": {
    "totalAssets": 2500000.00,
    "cashBalance": 100000.00,
    "stockValue": 2400000.00,
    "todayProfit": -25000.00,
    "totalProfit": 500000.00,
    "profitRate": 0.25,
    "marginRatio": 2.8,
    "riskLevel": "low",
    "maintenanceMargin": 850000.00,
    "availableMargin": 1650000.00
  }
}
```

### 组件二：服务适配层

#### BaseServiceAdapter 基类

```python
class BaseServiceAdapter(ABC):
    """服务适配器基类"""
    
    async def call(
        self,
        account_type: str,
        user_id: str,
        **params: Any,
    ) -> dict[str, Any]:
        """调用服务并标准化响应"""
        
    @abstractmethod
    def _normalize_response(
        self,
        raw_data: dict[str, Any],
        account_type: str,
    ) -> dict[str, Any]:
        """标准化字段名称（子类实现）"""
```

#### 字段标准化示例

```python
class AccountOverviewAdapter(BaseServiceAdapter):
    def _normalize_response(self, raw_data, account_type):
        data = raw_data.get("data", {})
        
        # 统一字段名称
        result = {
            "total_assets": data.get("totalAssets") or data.get("total_asset"),
            "cash_balance": data.get("cashBalance") or data.get("cash"),
            "stock_market_value": data.get("stockValue") or data.get("stock_mv"),
            # ...
        }
        
        # 两融账户额外字段
        if account_type == "margin":
            result["margin_ratio"] = data.get("marginRatio")
            result["risk_level"] = data.get("riskLevel")
        
        return result
```

### 组件三：工具层

#### 工具定义示例

```python
class AccountOverviewTool(AgentTool):
    """查询账户总资产"""
    
    name = "account_overview"
    description = "查询用户账户的总资产信息"
    parameters = [
        ToolParameter(name="user_id", type="string", required=True),
        ToolParameter(name="account_type", type="string", required=False, default="normal"),
    ]
    
    async def execute(self, tool_call, context=None):
        account_type = context.get("account_type", "normal")
        data = await self._adapter.call(
            account_type=account_type,
            user_id=context.get("user_id"),
        )
        return AgentToolResult.json_result(tool_call.id, data)
```

#### 工具列表

| 工具名称 | 功能 | 服务适配器 |
|---------|------|-----------|
| `account_overview` | 账户总资产 | AccountOverviewAdapter |
| `cash_assets` | 现金资产 | CashAssetsAdapter |
| `etf_holdings` | ETF 持仓 | ETFHoldingsAdapter |
| `hksc_holdings` | 港股通持仓 | HKSCHoldingsAdapter |
| `fund_holdings` | 基金理财 | FundHoldingsAdapter |
| `security_detail` | 具体标的 | SecurityDetailAdapter |

### 组件四：技能层

#### 资产总览技能

**触发条件**：用户询问账户资产、总资产、资产总览

**执行流程**：
1. 调用 `account_overview` 工具
2. 解析数据
3. 根据账户类型呈现结果

**输出示例**（普通账户）：
```markdown
## 您的资产总览

- 💰 **总资产**：¥1,250,000.00
- 💵 **可用资金**：¥50,000.00
- 📈 **持仓市值**：¥1,200,000.00
- 📊 **今日收益**：+¥15,000.00 (+1.2%)
- 🎯 **累计收益**：+¥250,000.00 (+25.0%)
```

**输出示例**（两融账户）：
```markdown
## 您的资产总览

- 💰 **总资产**：¥2,500,000.00
- 💵 **可用资金**：¥100,000.00
- 📈 **持仓市值**：¥2,400,000.00
- 📊 **今日收益**：-¥25,000.00 (-1.0%)
- 🎯 **累计收益**：+¥500,000.00 (+25.0%)

**两融账户风险指标**：
- 🛡️ **维持担保比率**：280%
- ⚠️ **风险等级**：低风险
```

### 组件五：响应格式处理

#### 模板渲染器

```python
class TemplateRenderer:
    """JSON 模板渲染器"""
    
    def should_render_template(
        self,
        user_input: str,
        intent: str | None = None,
    ) -> str | None:
        """判断是否应该渲染模板"""
        # 关键词匹配或 LLM 意图识别
        
    def render(
        self,
        template_name: str,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        """渲染模板"""
        return {
            "template_type": template_name,
            "data": data,
        }
```

#### SSE 事件扩展

```python
class SSEEvent(BaseModel):
    type: str  # response.template (新增)
    template_type: str | None = None
    template_data: dict[str, Any] | None = None
```

---

## 🔧 环境变量配置

```bash
# Mock 模式开关
SECURITIES_SERVICE_MOCK=true

# 账户总资产服务
SECURITIES_ACCOUNT_OVERVIEW_URL=https://api.example.com/account/overview
SECURITIES_ACCOUNT_OVERVIEW_AUTH_TYPE=header
SECURITIES_ACCOUNT_OVERVIEW_AUTH_KEY=Authorization
SECURITIES_ACCOUNT_OVERVIEW_AUTH_VALUE=Bearer xxx

# ETF 持仓服务
SECURITIES_ETF_HOLDINGS_URL=https://api.example.com/holdings/etf
SECURITIES_ETF_HOLDINGS_AUTH_TYPE=body
SECURITIES_ETF_HOLDINGS_AUTH_KEY=token
SECURITIES_ETF_HOLDINGS_AUTH_VALUE=xxx

# ... 其他服务配置
```

---

## 🧪 测试验证

### 1. Mock 数据测试

```bash
# 启动 Mock 模式
export SECURITIES_SERVICE_MOCK=true
python -m ark_agentic.agents.securities.agent -i

# 测试对话
[用户] 查看我的资产总览
[用户] 我的 ETF 持仓情况
[用户] 查询 510300 的持仓
```

### 2. API 测试

```bash
# 启动 API 服务
export SECURITIES_SERVICE_MOCK=true
ark-agentic-api

# 测试请求
curl -X POST http://localhost:8080/chat \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "securities",
    "message": "查看我的资产总览",
    "stream": false,
    "context": {"account_type": "normal"}
  }'
```

### 3. 流式响应测试

```bash
# 测试 SSE
curl -X POST http://localhost:8080/chat \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "securities",
    "message": "查看我的资产总览",
    "stream": true
  }'
```

**预期事件序列**：
1. `response.created`
2. `response.step`（工具调用）
3. `response.template`（如果触发模板）
4. `response.content.delta`（文本流）
5. `response.completed`

---

## 📅 实施计划

### 阶段一：基础架构（1-2 天）

- [x] 创建目录结构
- [ ] 实现 `MockDataLoader` 类
- [ ] 创建 Mock 数据文件（所有服务）
- [ ] 实现 `BaseServiceAdapter` 基类
- [ ] 实现 `MockServiceAdapter`
- [ ] 编写单元测试

### 阶段二：核心功能（2-3 天）

- [ ] 实现所有服务适配器
- [ ] 实现所有工具类
- [ ] 实现技能（资产总览、持仓分析、收益查询）
- [ ] 创建 Agent 配置
- [ ] 编写集成测试

### 阶段三：高级功能（1-2 天）

- [ ] 实现模板渲染器
- [ ] 创建 JSON 模板文件
- [ ] 集成到 API（SSE 扩展）
- [ ] 在 `app.py` 注册 securities agent
- [ ] 测试流式响应

### 阶段四：测试和文档（1 天）

- [ ] 手动测试所有场景
- [ ] 编写使用文档
- [ ] 编写服务对接文档
- [ ] 更新项目 README

---

## ⚠️ 风险和注意事项

1. **服务接口差异**：不同团队的接口可能差异很大，适配器需要足够灵活
2. **字段命名混乱**：建议先与服务提供方沟通，统一命名规范
3. **两融账户复杂性**：建议先实现普通账户，验证通过后再扩展两融
4. **前端协议对齐**：JSON 模板格式需要与 AG-UI 团队确认
5. **性能考虑**：多个服务调用可能较慢，考虑并发调用或缓存

---

## 🚀 后续优化方向

1. **服务调用优化**：
   - 实现连接池
   - 添加重试机制
   - 实现缓存层

2. **智能推荐**：
   - 基于持仓分析提供投资建议
   - 风险预警（两融账户）

3. **数据可视化**：
   - 收益曲线图
   - 持仓分布饼图

4. **多账户支持**：
   - 支持用户管理多个证券账户
   - 账户间资产对比

---

## 📞 联系和支持

如有问题或建议，请联系开发团队。

**文档版本**: v1.0  
**最后更新**: 2026-02-14
