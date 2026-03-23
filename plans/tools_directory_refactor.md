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

### 3.1 tools/__init__.py

只导出 AgentTool，供 agent.py 使用：

```python
"""证券智能体工具"""

from .agent import (
    AccountOverviewTool,
    ETFHoldingsTool,
    HKSCHoldingsTool,
    FundHoldingsTool,
    CashAssetsTool,
    SecurityDetailTool,
    BranchInfoTool,
    DisplayCardTool,
    create_securities_tools,
)

__all__ = [
    "AccountOverviewTool",
    "ETFHoldingsTool",
    "HKSCHoldingsTool",
    "FundHoldingsTool",
    "CashAssetsTool",
    "SecurityDetailTool",
    "BranchInfoTool",
    "DisplayCardTool",
    "create_securities_tools",
]
```

### 3.2 tools/agent/__init__.py

```python
"""智能体工具 (AgentTool)"""

from .account_overview import AccountOverviewTool
from .etf_holdings import ETFHoldingsTool
from .hksc_holdings import HKSCHoldingsTool
from .fund_holdings import FundHoldingsTool
from .cash_assets import CashAssetsTool
from .security_detail import SecurityDetailTool
from .branch_info import BranchInfoTool
from .display_card import DisplayCardTool

__all__ = [
    "AccountOverviewTool",
    "ETFHoldingsTool",
    "HKSCHoldingsTool",
    "FundHoldingsTool",
    "CashAssetsTool",
    "SecurityDetailTool",
    "BranchInfoTool",
    "DisplayCardTool",
    "create_securities_tools",
]


def create_securities_tools() -> list:
    """创建所有证券工具"""
    return [
        AccountOverviewTool(),
        ETFHoldingsTool(),
        HKSCHoldingsTool(),
        FundHoldingsTool(),
        CashAssetsTool(),
        SecurityDetailTool(),
        BranchInfoTool(),
        DisplayCardTool(),
    ]
```

### 3.3 tools/service/base.py

抽取公共基类和工具方法：

```python
"""服务适配器基类和公共工具"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class ServiceConfig:
    """服务配置"""
    
    def __init__(
        self,
        url: str,
        auth_type: str = "header",
        auth_key: str = "Authorization",
        auth_value: str | None = None,
        timeout: float = 30.0,
    ):
        self.url = url
        self.auth_type = auth_type
        self.auth_key = auth_key
        self.auth_value = auth_value
        self.timeout = timeout


class ServiceError(Exception):
    """服务调用异常"""
    pass


class BaseServiceAdapter(ABC):
    """服务适配器基类"""
    
    http_method: str = "POST"
    
    def __init__(self, config: ServiceConfig):
        self.config = config
        self._http: httpx.AsyncClient | None = None
    
    async def _get_http(self) -> httpx.AsyncClient:
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(
                timeout=httpx.Timeout(self.config.timeout, connect=10.0)
            )
        return self._http
    
    async def call(
        self,
        account_type: str,
        user_id: str,
        **params: Any,
    ) -> dict[str, Any]:
        """调用服务接口"""
        client = await self._get_http()
        headers, payload = self._build_request(account_type, user_id, params)
        
        try:
            if self.http_method == "GET":
                resp = await client.get(
                    self.config.url,
                    params=payload,
                    headers=headers,
                )
            else:
                resp = await client.post(
                    self.config.url,
                    json=payload,
                    headers=headers,
                )
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.error(...)
            raise ServiceError(f"HTTP {exc.response.status_code}: ...") from exc
        except httpx.RequestError as exc:
            logger.error(...)
            raise ServiceError(f"Request failed: {exc}") from exc
        
        raw_data = resp.json()
        return self._normalize_response(raw_data, account_type)
    
    def _build_request(
        self,
        account_type: str,
        user_id: str,
        params: dict[str, Any],
    ) -> tuple[dict[str, str], dict[str, Any]]:
        """默认实现，子类可覆盖"""
        headers = {"Content-Type": "application/json"}
        payload = {"user_id": user_id, "account_type": account_type, **params}
        
        if self.config.auth_type == "header":
            headers[self.config.auth_key] = self.config.auth_value or ""
        else:
            payload[self.config.auth_key] = self.config.auth_value or ""
        
        return headers, payload
    
    @abstractmethod
    def _normalize_response(
        self,
        raw_data: dict[str, Any],
        account_type: str,
    ) -> dict[str, Any]:
        """标准化响应数据（子类实现）"""
        pass
    
    async def close(self):
        if self._http and not self._http.is_closed:
            await self._http.aclose()


# ============ 公共工具方法 ============

def require_context_fields(
    context: dict[str, Any],
    fields: list[str],
    service_name: str = "",
) -> None:
    """校验 context 中必需字段"""
    from .mock_mode import get_mock_mode_for_context
    from .param_mapping import get_context_value
    
    if get_mock_mode_for_context(context):
        return
    
    missing = [f for f in fields if not get_context_value(context, f)]
    if missing:
        prefix = f"[{service_name}] " if service_name else ""
        raise ValueError(f"{prefix}context 缺少必需字段: {', '.join(missing)}")


def build_validatedata_request(
    service_name: str,
    context: dict[str, Any],
    account_type: str | None = None,
) -> tuple[dict[str, str], dict[str, Any]]:
    """构建 validatedata + signature 认证请求
    
    公共方法，供所有需要这种认证方式的 Adapter 使用。
    
    Args:
        service_name: 服务名称 (account_overview, etf_holdings 等)
        context: 请求上下文
        account_type: 账户类型 (可选，某些服务需要)
    
    Returns:
        (headers, body) 元组
    """
    from .param_mapping import (
        build_api_request,
        build_api_headers_with_validatedata,
        SERVICE_PARAM_CONFIGS,
        SERVICE_HEADER_CONFIGS,
    )
    
    require_context_fields(context, ["validatedata"], service_name)
    
    # 确保扁平结构中有 account_type
    if account_type and "account_type" not in context:
        context = {**context, "account_type": account_type}
    
    # 构建请求体
    config = SERVICE_PARAM_CONFIGS.get(service_name, {})
    body = build_api_request(config, context)
    
    # 构建 headers
    headers = {"Content-Type": "application/json"}
    header_config = SERVICE_HEADER_CONFIGS.get(service_name, {})
    auth_headers = build_api_headers_with_validatedata(header_config, context)
    headers.update(auth_headers)
    
    return headers, body


def check_api_response(raw_data: dict[str, Any]) -> None:
    """检查 API 响应状态"""
    if raw_data.get("status") != 1:
        error_msg = (
            raw_data.get("errmsg") 
            or raw_data.get("msg") 
            or raw_data.get("errMsg")
            or "Unknown API error"
        )
        raise ServiceError(f"API returned error: {error_msg}")
```

### 3.4 tools/service/mock_mode.py

```python
"""Mock 模式判断"""

import os
from typing import Any


def get_mock_mode() -> bool:
    """服务级默认 mock 状态"""
    return os.getenv("SECURITIES_SERVICE_MOCK", "").lower() in ("true", "1")


def get_mock_mode_for_context(context: dict | None = None) -> bool:
    """per-request mock 模式解析
    
    优先级：
    1. context 中的 user:mock_mode（per-session 覆盖）
    2. SECURITIES_SERVICE_MOCK 环境变量（服务级默认）
    """
    if context:
        val = context.get("user:mock_mode") or context.get("mock_mode")
        if val is not None:
            return str(val).lower() in ("true", "1")
    return get_mock_mode()
```

### 3.5 tools/service/adapters/account_overview.py

拆分后的适配器示例：

```python
"""账户总资产服务适配器"""

from __future__ import annotations

from typing import Any

from ..base import (
    BaseServiceAdapter,
    ServiceConfig,
    build_validatedata_request,
    check_api_response,
)


class AccountOverviewAdapter(BaseServiceAdapter):
    """账户总资产服务适配器"""
    
    def _build_request(
        self,
        account_type: str,
        user_id: str,
        params: dict[str, Any],
    ) -> tuple[dict[str, str], dict[str, Any]]:
        context = params.get("_context", {})
        return build_validatedata_request(
            service_name="account_overview",
            context=context,
            account_type=account_type,
        )
    
    def _normalize_response(
        self,
        raw_data: dict[str, Any],
        account_type: str,
    ) -> dict[str, Any]:
        check_api_response(raw_data)
        return raw_data
```

### 3.6 tools/service/adapters/__init__.py

```python
"""API 适配器"""

from .account_overview import AccountOverviewAdapter
from .etf_holdings import ETFHoldingsAdapter
from .hksc_holdings import HKSCHoldingsAdapter
from .fund_holdings import FundHoldingsAdapter
from .cash_assets import CashAssetsAdapter
from .security_detail import SecurityDetailAdapter
from .branch_info import BranchInfoAdapter

# 适配器注册表
ADAPTER_REGISTRY = {
    "account_overview": AccountOverviewAdapter,
    "etf_holdings": ETFHoldingsAdapter,
    "hksc_holdings": HKSCHoldingsAdapter,
    "fund_holdings": FundHoldingsAdapter,
    "cash_assets": CashAssetsAdapter,
    "security_detail": SecurityDetailAdapter,
    "branch_info": BranchInfoAdapter,
}

__all__ = [
    "AccountOverviewAdapter",
    "ETFHoldingsAdapter",
    "HKSCHoldingsAdapter",
    "FundHoldingsAdapter",
    "CashAssetsAdapter",
    "SecurityDetailAdapter",
    "BranchInfoAdapter",
    "ADAPTER_REGISTRY",
]
```

### 3.7 tools/service/__init__.py

```python
"""服务基础设施"""

from .base import (
    ServiceConfig,
    BaseServiceAdapter,
    ServiceError,
    require_context_fields,
    build_validatedata_request,
    check_api_response,
)
from .mock_mode import get_mock_mode, get_mock_mode_for_context
from .mock_loader import get_mock_loader, MockServiceAdapter
from .adapters import ADAPTER_REGISTRY

__all__ = [
    "ServiceConfig",
    "BaseServiceAdapter",
    "ServiceError",
    "require_context_fields",
    "build_validatedata_request",
    "check_api_response",
    "get_mock_mode",
    "get_mock_mode_for_context",
    "get_mock_loader",
    "MockServiceAdapter",
    "ADAPTER_REGISTRY",
    "create_service_adapter",
]


def create_service_adapter(
    service_name: str,
    context: dict | None = None,
) -> BaseServiceAdapter:
    """创建服务适配器"""
    import logging
    import os
    
    logger = logging.getLogger(__name__)
    
    is_mock = get_mock_mode_for_context(context)
    source = "session" if context and context.get("user:mock_mode") else "env_default"
    mode_label = "[MOCK]" if is_mock else "[API] "
    logger.info("%s tool=%-20s source=%s", mode_label, service_name, source)
    
    if is_mock:
        return MockServiceAdapter(service_name)
    
    url = os.getenv(f"SECURITIES_{service_name.upper()}_URL")
    if not url:
        raise ValueError(f"Missing environment variable: SECURITIES_{service_name.upper()}_URL")
    
    config = ServiceConfig(
        url=url,
        auth_type=os.getenv(f"SECURITIES_{service_name.upper()}_AUTH_TYPE", "header"),
        auth_key=os.getenv(f"SECURITIES_{service_name.upper()}_AUTH_KEY", "Authorization"),
        auth_value=os.getenv(f"SECURITIES_{service_name.upper()}_AUTH_VALUE"),
    )
    
    adapter_class = ADAPTER_REGISTRY.get(service_name)
    if adapter_class:
        return adapter_class(config)
    
    raise ValueError(f"Unknown service: {service_name}")
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

### 4.4 更新文件

| 文件 | 变更 |
|------|------|
| `tools/__init__.py` | 从 `tools/agent` 导入 |
| `tools/agent/*.py` | 更新 import 路径 |

---

## 五、import 路径变更

### 5.1 AgentTool 文件

```python
# 之前
from .service_client import create_service_adapter

# 之后
from ..service import create_service_adapter
```

### 5.2 外部调用

```python
# 之前
from ark_agentic.agents.securities.tools import AccountOverviewTool

# 之后 (保持不变)
from ark_agentic.agents.securities.tools import AccountOverviewTool
```

---

## 六、实施顺序

### Phase 1: 创建新目录结构

- [ ] 1.1 创建 `tools/agent/` 目录
- [ ] 1.2 创建 `tools/service/` 目录
- [ ] 1.3 创建 `tools/service/adapters/` 目录

### Phase 2: 创建基础设施文件

- [ ] 2.1 创建 `tools/service/base.py`
  - [ ] 迁移 `ServiceConfig`, `BaseServiceAdapter`, `ServiceError`
  - [ ] 实现 `require_context_fields`
  - [ ] 实现 `build_validatedata_request`
  - [ ] 实现 `check_api_response`
  
- [ ] 2.2 创建 `tools/service/mock_mode.py`
  - [ ] 迁移 `get_mock_mode`, `get_mock_mode_for_context`
  
- [ ] 2.3 移动 `mock_loader.py` → `tools/service/mock_loader.py`
- [ ] 2.4 移动 `param_mapping.py` → `tools/service/param_mapping.py`
- [ ] 2.5 移动 `field_extraction.py` → `tools/service/field_extraction.py`

### Phase 3: 创建适配器文件

- [ ] 3.1 创建 `tools/service/adapters/__init__.py`
- [ ] 3.2 拆分 `AccountOverviewAdapter` → `adapters/account_overview.py`
- [ ] 3.3 拆分 `ETFHoldingsAdapter` → `adapters/etf_holdings.py`
- [ ] 3.4 拆分 `HKSCHoldingsAdapter` → `adapters/hksc_holdings.py`
- [ ] 3.5 拆分 `FundHoldingsAdapter` → `adapters/fund_holdings.py`
- [ ] 3.6 拆分 `CashAssetsAdapter` → `adapters/cash_assets.py`
- [ ] 3.7 拆分 `SecurityDetailAdapter` → `adapters/security_detail.py`
- [ ] 3.8 拆分 `BranchInfoAdapter` → `adapters/branch_info.py`
- [ ] 3.9 创建 `MockServiceAdapter` 在 `mock_loader.py`

### Phase 4: 移动 AgentTool 文件

- [ ] 4.1 移动所有 AgentTool 文件到 `tools/agent/`
- [ ] 4.2 更新各文件的 import 路径
- [ ] 4.3 创建 `tools/agent/__init__.py`

### Phase 5: 更新导出

- [ ] 5.1 更新 `tools/__init__.py`
- [ ] 5.2 创建 `tools/service/__init__.py`

### Phase 6: 清理

- [ ] 6.1 删除 `tools/service_client.py`
- [ ] 6.2 删除原 `tools/` 下的旧文件
- [ ] 6.3 运行测试验证

---

## 七、验收标准

1. **目录结构正确**
   - `tools/agent/` 包含所有 AgentTool
   - `tools/service/` 包含所有基础设施
   - `tools/service/adapters/` 包含所有适配器

2. **功能正常**
   - 所有测试通过
   - 外部 import 路径不变

3. **代码质量**
   - 每个 Adapter 文件 < 100 行
   - 无重复代码
   - 公共方法抽取到 `base.py`

---

## 八、后续工作

此重构完成后，再实施：

1. 工具合并方案 (`account_query`, `holdings`)
2. profit_inquiry 技能扩展

---

## 九、风险与缓解

| 风险 | 缓解措施 |
|------|----------|
| import 路径变更导致错误 | 分步迁移，每步运行测试 |
| 适配器拆分后行为不一致 | 保持原有逻辑，只做结构变更 |
| 遗漏某些 import | grep 搜索所有引用 |