# 工具合并与 profit_inquiry 技能扩展实施方案

> 创建时间: 2024-03-17
> 状态: 待实施

## 一、背景

### 当前问题

1. **工具数量多**: 证券智能体有 8 个工具，其中多个工具功能相似
2. **历史查询缺失**: profit_inquiry 仅支持今日收益查询，无法查询历史区间收益
3. **新增 API**: 后台服务新增 `asset_history` API，支持任意时间区间的总资产变化查询

### 目标

1. 合并相似工具，从 8 个减少到 6 个
2. 扩展 profit_inquiry 技能，支持历史区间收益查询
3. 保持向后兼容，不影响现有功能

---

## 二、工具层合并

### 2.1 新增 `account_query` 工具

**合并**: `account_overview` + `asset_history`

**文件**: `src/ark_agentic/agents/securities/tools/account_query.py`

```python
class AccountQueryTool(AgentTool):
    """查询账户资产信息（支持今日和历史区间）"""
    
    name = "account_query"
    description = "查询用户账户的总资产信息。支持今日总览和历史区间查询。"
    parameters = [
        ToolParameter(
            name="time_range",
            type="string",
            description="时间范围: today(今日)/week(本周)/month(本月)/year(本年)/custom(自定义)",
            required=False,
        ),
        ToolParameter(
            name="start_date",
            type="string",
            description="起始日期(YYYY-MM-DD)，time_range=custom时必填",
            required=False,
        ),
        ToolParameter(
            name="end_date",
            type="string", 
            description="结束日期(YYYY-MM-DD)，time_range=custom时必填",
            required=False,
        ),
    ]
```

**参数说明**:

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| time_range | string | 否 | 默认 today，可选: week/month/year/custom |
| start_date | string | 条件 | time_range=custom 时必填 |
| end_date | string | 条件 | time_range=custom 时必填 |

**返回结构**:

```python
# time_range = "today" (现有 account_overview 返回)
{
    "total_asset": 684000,
    "cash": 213000,
    "market_value": 471000,
    "today_profit": 1240,
    "today_profit_rate": 0.0026,
    # 两融账户额外字段
    "net_asset": 521000,
    "total_debt": 163000,
    "maintenance_ratio": 3.18,
    "risk_level": "normal",
}

# time_range = "week/month/year/custom" (新增)
{
    "start_date": "2024-01-01",
    "end_date": "2024-03-31",
    "start_asset": 650000,
    "end_asset": 678000,
    "profit": 28000,
    "profit_rate": 0.0431,
}
```

### 2.2 新增 `holdings` 工具

**合并**: `etf_holdings` + `hksc_holdings` + `fund_holdings`

**文件**: `src/ark_agentic/agents/securities/tools/holdings.py`

```python
class HoldingsTool(AgentTool):
    """查询持仓明细"""
    
    name = "holdings"
    description = "查询用户持仓明细。支持ETF、港股通、基金三种资产类型。"
    parameters = [
        ToolParameter(
            name="asset_type",
            type="string",
            description="资产类型: etf(ETF)/hksc(港股通)/fund(基金)",
            required=True,
        ),
    ]
```

**参数说明**:

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| asset_type | string | 是 | etf/hksc/fund |

**返回结构** (与现有持仓工具一致):

```python
{
    "asset_type": "etf",
    "items": [
        {
            "code": "510050",
            "name": "50ETF",
            "quantity": 10000,
            "cost": 2.50,
            "price": 2.65,
            "market_value": 26500,
            "profit": 1500,
            "profit_rate": 0.06,
        },
    ],
    "total_market_value": 265000,
    "total_profit": 15000,
}
```

### 2.3 保留独立工具

| 工具 | 说明 | 文件 |
|------|------|------|
| cash_assets | 现金资产查询 | cash_assets.py |
| security_detail | 标的详情查询 | security_detail.py |
| branch_info | 分支信息查询 | branch_info.py |
| display_card | 前端卡片展示 | display_card.py |

### 2.4 废弃工具

| 废弃工具 | 替代方案 |
|----------|----------|
| account_overview | account_query(time_range="today") |
| etf_holdings | holdings(asset_type="etf") |
| hksc_holdings | holdings(asset_type="hksc") |
| fund_holdings | holdings(asset_type="fund") |

### 2.5 更新工具注册

**文件**: `src/ark_agentic/agents/securities/tools/__init__.py`

```python
from .account_query import AccountQueryTool
from .holdings import HoldingsTool
from .cash_assets import CashAssetsTool
from .security_detail import SecurityDetailTool
from .branch_info import BranchInfoTool
from .display_card import DisplayCardTool

__all__ = [
    "AccountQueryTool",
    "HoldingsTool", 
    "CashAssetsTool",
    "SecurityDetailTool",
    "BranchInfoTool",
    "DisplayCardTool",
    "create_securities_tools",
]

def create_securities_tools() -> list:
    return [
        AccountQueryTool(),
        HoldingsTool(),
        CashAssetsTool(),
        SecurityDetailTool(),
        BranchInfoTool(),
        DisplayCardTool(),
    ]
```

### 2.6 Mock 数据

**目录**: `src/ark_agentic/agents/securities/mock_data/`

新增:
- `account_query_history/` - 历史区间查询 Mock 数据
- 复用现有 `account_overview/` 数据作为 today 场景

---

## 三、技能层修改

### 3.1 修改 `profit_inquiry` 技能

**文件**: `src/ark_agentic/agents/securities/skills/profit_inquiry/SKILL.md`

#### 3.1.1 意图模型扩展

```yaml
intent_schema:
  time_range:          # 新增维度
    enum:
      - TODAY          # 今日（默认）
      - WEEK           # 本周
      - MONTH          # 本月
      - YEAR           # 本年
      - CUSTOM         # 自定义区间

  scope:               # 保持不变
    enum:
      - TOTAL          # 总收益
      - ASSET_TYPE     # 单类资产收益

  mode:                # 保持不变
    enum:
      - MODE_CARD
      - MODE_TEXT
```

#### 3.1.2 时间范围判断规则

```yaml
time_range 判断规则:
  默认值: TODAY
  
  触发词映射:
    - "今天/今日/当日" → TODAY
    - "本周/这周/这星期" → WEEK  
    - "本月/这个月" → MONTH
    - "本年/今年/今年以来" → YEAR
    - "X月到Y月/X号到Y号/从X到Y" → CUSTOM (LLM解析具体日期)
```

#### 3.1.3 约束规则

```
当 time_range != TODAY 时：
  - scope 必须为 TOTAL（API 不支持分类历史查询）
  - 若用户问"上周ETF收益"，回复："暂不支持按资产类型查询历史收益，可查询账户整体历史收益。"
```

#### 3.1.4 工具契约更新

```
| 工具                         | 用途                              |
| ---------------------------- | --------------------------------- |
| account_query(time_range)    | 账户收益查询（今日/历史）         |
| holdings(asset_type)         | 分类资产持仓及收益                |
```

#### 3.1.5 执行流程更新

```
STEP_1_INTENT_PARSE
        ↓
STEP_2_FETCH_DATA
        │
        ├─ time_range == TODAY
        │       ├─ scope=TOTAL → account_query("today")
        │       └─ scope=ASSET_TYPE → holdings(asset_type)
        │
        └─ time_range != TODAY
                └─ 必须验证 scope=TOTAL
                └─ 若 scope=ASSET_TYPE → 提示不支持
                └─ account_query(time_range, start?, end?)
        ↓
    MODE_CARD / MODE_TEXT
```

#### 3.1.6 MODE_TEXT 输出示例补充

```
示例（本月收益）：
> 本月您的账户总资产从68.4万增长至69.2万，累计收益+8,240元（+1.20%）。

示例（今年收益）：
> 今年以来您的账户总资产从60.0万增长至69.2万，累计收益+92,000元（+15.33%）。

示例（自定义区间）：
> 2024年1月1日至3月31日，您的账户总资产从65.0万增长至67.8万，累计收益+28,000元（+4.31%）。
```

#### 3.1.7 路由边界补充

```
| 用户问题               | 处理方式                              |
| ---------------------- | ------------------------------------- |
| 上周ETF收益            | 提示"暂不支持分类历史查询"            |
| 这个月赚了多少         | time_range=MONTH, scope=TOTAL         |
| 今年收益率怎么样       | time_range=YEAR, scope=TOTAL, MODE_TEXT |
| 1月到3月收益           | time_range=CUSTOM, LLM解析日期        |
```

### 3.2 修改 `asset_overview` 技能

**文件**: `src/ark_agentic/agents/securities/skills/asset_overview/SKILL.md`

#### 3.2.1 工具契约更新

```
| 工具                         | 用途                |
| ---------------------------- | ------------------- |
| account_query("today")       | 获取账户总资产数据  |
```

#### 3.2.2 其他

- 执行流程中的 `account_overview()` 改为 `account_query("today")`
- 其他逻辑不变

### 3.3 修改 `holdings_analysis` 技能

**文件**: `src/ark_agentic/agents/securities/skills/holdings_analysis/SKILL.md`

#### 3.3.1 工具契约更新

```
| 工具                    | 用途               |
| ----------------------- | ------------------ |
| holdings(asset_type)    | 获取持仓明细       |
```

#### 3.3.2 其他

- 执行流程中的 `etf_holdings()` / `hksc_holdings()` / `fund_holdings()` 改为 `holdings(asset_type)`
- 其他逻辑不变

---

## 四、工具清单对比

| 修改前 | 修改后 | 变化 |
|--------|--------|------|
| account_overview | account_query | 合并 |
| etf_holdings | holdings | 合并 |
| hksc_holdings | ↑ | 废弃 |
| fund_holdings | ↑ | 废弃 |
| cash_assets | cash_assets | 保留 |
| security_detail | security_detail | 保留 |
| branch_info | branch_info | 保留 |
| display_card | display_card | 保留 |
| **8个** | **6个** | **-2** |

---

## 五、实施顺序

### Phase 1: 工具层 (预计 2-3 小时)

- [ ] 1.1 新建 `account_query.py`
  - [ ] 定义工具类和参数
  - [ ] 实现 today 场景（复用现有 account_overview 逻辑）
  - [ ] 实现 history 场景（对接新 API 或 Mock）
  - [ ] 添加错误处理

- [ ] 1.2 新建 `holdings.py`
  - [ ] 定义工具类和参数
  - [ ] 复用现有持仓工具逻辑
  - [ ] 统一返回格式

- [ ] 1.3 添加 Mock 数据
  - [ ] `mock_data/account_query_history/`
  - [ ] 测试数据文件

- [ ] 1.4 更新 `__init__.py`
  - [ ] 导出新工具类
  - [ ] 更新 `create_securities_tools()`

- [ ] 1.5 保留旧工具文件（暂不删除）
  - [ ] 标记为 deprecated
  - [ ] 内部调用新工具实现兼容

### Phase 2: 技能层 (预计 1-2 小时)

- [ ] 2.1 修改 `profit_inquiry/SKILL.md`
  - [ ] 更新意图模型
  - [ ] 更新工具契约
  - [ ] 更新执行流程
  - [ ] 添加约束规则
  - [ ] 添加输出示例

- [ ] 2.2 修改 `asset_overview/SKILL.md`
  - [ ] 更新工具契约
  - [ ] 更新工具调用示例

- [ ] 2.3 修改 `holdings_analysis/SKILL.md`
  - [ ] 更新工具契约
  - [ ] 更新工具调用示例

### Phase 3: 测试 (预计 1 小时)

- [ ] 3.1 编写测试用例
  - [ ] account_query today 场景
  - [ ] account_query history 场景
  - [ ] holdings 各资产类型

- [ ] 3.2 运行静态评估
  - [ ] profit_inquiry 技能评估
  - [ ] asset_overview 技能评估
  - [ ] holdings_analysis 技能评估

- [ ] 3.3 集成测试
  - [ ] SECURITIES_SERVICE_MOCK=true 运行测试

### Phase 4: 清理 (预计 0.5 小时)

- [ ] 4.1 删除废弃工具文件
  - [ ] account_overview.py
  - [ ] etf_holdings.py
  - [ ] hksc_holdings.py
  - [ ] fund_holdings.py

- [ ] 4.2 更新相关文档

---

## 六、风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 新工具参数解析错误 | 查询失败 | 参数校验 + 默认值兜底 |
| LLM 日期解析不准确 | CUSTOM 场景异常 | 提供日期格式提示 + 示例 |
| 向后兼容问题 | 旧调用失败 | 保留旧工具名作为别名 |
| Mock 数据不一致 | 测试结果偏差 | 复用现有 Mock 数据结构 |

---

## 七、验收标准

1. **工具层**
   - account_query 支持 today/week/month/year/custom 五种时间范围
   - holdings 支持 etf/hksc/fund 三种资产类型
   - 所有工具返回结构正确

2. **技能层**
   - profit_inquiry 支持历史收益查询
   - asset_overview 正常调用 account_query
   - holdings_analysis 正常调用 holdings

3. **测试**
   - 静态评估通过率 100%
   - 集成测试通过

---

## 八、参考文档

- 现有技能: `src/ark_agentic/agents/securities/skills/`
- 现有工具: `src/ark_agentic/agents/securities/tools/`
- 测试用例: `tests/skills/`