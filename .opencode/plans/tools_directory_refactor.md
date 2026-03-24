# tools 目录重构方案

> 创建时间: 2024-03-17
> 状态: 待实施
> 优先级: 先于此前的工具合并方案

## 一、当前问题

### 1.1 目录结构混乱

`tools/` 目录混合了两种不同职责的代码：

| 类型 | 文件 | 行数 | 职责 |
|------|------|------|------|
| **智能体工具** | account_overview.py | 106 | AgentTool 实现，供 LLM 调用 |
| | etf_holdings.py | 98 | AgentTool 实现 |
| | hksc_holdings.py | 96 | AgentTool 实现 |
| | fund_holdings.py | 95 | AgentTool 实现 |
| | cash_assets.py | 95 | AgentTool 实现 |
| | security_detail.py | 102 | AgentTool 实现 |
| | branch_info.py | 60 | AgentTool 实现 |
| | display_card.py | 185 | AgentTool 实现 |
| **基础设施** | service_client.py | **731** | API 适配器、HTTP 客户端 |
| | param_mapping.py | 402 | 参数映射工具 |
| | field_extraction.py | 368 | 字段提取工具 |
| | mock_loader.py | 103 | Mock 数据加载器 |

### 1.2 service_client.py 过大

- **731 行代码**，包含 7 个 Adapter 类
- 每个 Adapter 的 `_build_request` 方法有大量重复代码
- 认证逻辑 (validatedata + signature) 在每个类中重复实现
- 难以维护和扩展

---

## 二、目标结构

```
src/ark_agentic/agents/securities/tools/
├── __init__.py                    # 只导出 AgentTool
│
├── agent/                         # 智能体工具 (AgentTool)
│   ├── __init__.py
│   ├── account_overview.py
│   ├── etf_holdings.py
│   ├── hksc_holdings.py
│   ├── fund_holdings.py
│   ├── cash_assets.py
│   ├── security_detail.py
│   ├── branch_info.py
│   └── display_card.py
│
└── service/                       # 服务基础设施
    ├── __init__.py
    ├── base.py                    # BaseServiceAdapter, ServiceConfig, ServiceError
    ├── mock_loader.py             # Mock 加载器
    ├── mock_mode.py               # Mock 模式判断工具函数
    │
    ├── adapters/                  # API 适配器 (每个独立文件)
    │   ├── __init__.py
    │   ├── account_overview.py
    │   ├── etf_holdings.py
    │   ├── hksc_holdings.py
    │   ├── fund_holdings.py
    │   ├── cash_assets.py
    │   ├── security_detail.py
    │   └── branch_info.py
    │
    ├── param_mapping.py           # 参数映射
    └── field_extraction.py        # 字段提取
```

---

## 三、详细设计

### 3.1 tools/service/base.py

抽取公共基类和工具方法：

```python
"""服务适配器基类和公共工具"""

class ServiceConfig:
    """服务配置"""
    pass

class ServiceError(Exception):
    """服务调用异常"""
    pass

class BaseServiceAdapter(ABC):
    """服务适配器基类"""
    pass

# ============ 公共工具方法 ============

def require_context_fields(context, fields, service_name=""):
    """校验 context 中必需字段"""
    pass

def build_validatedata_request(service_name, context, account_type=None):
    """构建 validatedata + signature 认证请求
    
    公共方法，供所有需要这种认证方式的 Adapter 使用。
    """
    pass

def check_api_response(raw_data):
    """检查 API 响应状态"""
    pass
```

### 3.2 tools/service/adapters/account_overview.py

拆分后的适配器示例：

```python
"""账户总资产服务适配器"""

from ..base import (
    BaseServiceAdapter,
    ServiceConfig,
    build_validatedata_request,
    check_api_response,
)

class AccountOverviewAdapter(BaseServiceAdapter):
    """账户总资产服务适配器"""
    
    def _build_request(self, account_type, user_id, params):
        context = params.get("_context", {})
        return build_validatedata_request(
            service_name="account_overview",
            context=context,
            account_type=account_type,
        )
    
    def _normalize_response(self, raw_data, account_type):
        check_api_response(raw_data)
        return raw_data
```

---

## 四、文件变更清单

### 4.1 新建文件

| 文件 | 说明 |
|------|------|
| `tools/agent/__init__.py` | AgentTool 导出 |
| `tools/service/__init__.py` | 服务基础设施导出 |
| `tools/service/base.py` | 基类和公共方法 |
| `tools/service/mock_mode.py` | Mock 模式判断 |
| `tools/service/adapters/__init__.py` | 适配器导出 |
| `tools/service/adapters/account_overview.py` | 账户总资产适配器 |
| `tools/service/adapters/etf_holdings.py` | ETF 适配器 |
| `tools/service/adapters/hksc_holdings.py` | 港股通适配器 |
| `tools/service/adapters/fund_holdings.py` | 基金适配器 |
| `tools/service/adapters/cash_assets.py` | 现金适配器 |
| `tools/service/adapters/security_detail.py` | 标的详情适配器 |
| `tools/service/adapters/branch_info.py` | 分支信息适配器 |

### 4.2 移动文件

| 原位置 | 新位置 |
|--------|--------|
| `tools/account_overview.py` | `tools/agent/account_overview.py` |
| `tools/etf_holdings.py` | `tools/agent/etf_holdings.py` |
| `tools/hksc_holdings.py` | `tools/agent/hksc_holdings.py` |
| `tools/fund_holdings.py` | `tools/agent/fund_holdings.py` |
| `tools/cash_assets.py` | `tools/agent/cash_assets.py` |
| `tools/security_detail.py` | `tools/agent/security_detail.py` |
| `tools/branch_info.py` | `tools/agent/branch_info.py` |
| `tools/display_card.py` | `tools/agent/display_card.py` |
| `tools/mock_loader.py` | `tools/service/mock_loader.py` |
| `tools/param_mapping.py` | `tools/service/param_mapping.py` |
| `tools/field_extraction.py` | `tools/service/field_extraction.py` |

### 4.3 删除文件

| 文件 | 原因 |
|------|------|
| `tools/service_client.py` | 拆分到 `base.py` + `adapters/*.py` |

---

## 五、实施顺序

### Phase 1: 创建新目录结构

- [ ] 1.1 创建 `tools/agent/` 目录
- [ ] 1.2 创建 `tools/service/` 目录
- [ ] 1.3 创建 `tools/service/adapters/` 目录

### Phase 2: 创建基础设施文件

- [ ] 2.1 创建 `tools/service/base.py`
- [ ] 2.2 创建 `tools/service/mock_mode.py`
- [ ] 2.3 移动 `mock_loader.py`
- [ ] 2.4 移动 `param_mapping.py`
- [ ] 2.5 移动 `field_extraction.py`

### Phase 3: 创建适配器文件

- [ ] 3.1 创建 `tools/service/adapters/__init__.py`
- [ ] 3.2-3.9 拆分各适配器到独立文件

### Phase 4: 移动 AgentTool 文件

- [ ] 4.1 移动所有 AgentTool 文件到 `tools/agent/`
- [ ] 4.2 更新各文件的 import 路径

### Phase 5: 更新导出

- [ ] 5.1 更新 `tools/__init__.py`
- [ ] 5.2 创建 `tools/service/__init__.py`

### Phase 6: 清理

- [ ] 6.1 删除 `tools/service_client.py`
- [ ] 6.2 运行测试验证

---

## 六、验收标准

1. 每个 Adapter 文件 < 100 行
2. 无重复代码
3. 所有测试通过
4. 外部 import 路径不变

---

## 七、后续工作

此重构完成后，再实施：

1. 工具合并方案 (`account_query`, `holdings`)
2. profit_inquiry 技能扩展