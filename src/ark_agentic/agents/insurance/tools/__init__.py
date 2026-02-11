"""
保险业务工具

提供保险场景相关的工具实现。

工具列表：
- PolicyQueryTool: 保单查询（列表、详情、现金价值、可取款额度）
- RuleEngineTool: 规则引擎（计算取款方案、比较方案）
- CustomerInfoTool: 客户信息（身份、联系方式、受益人、交易历史）
"""

from .data_service import DataServiceClient, MockDataServiceClient, get_data_service_client
from .policy_query import PolicyQueryTool
from .rule_engine import RuleEngineTool
from .customer_info import CustomerInfoTool

__all__ = [
    "DataServiceClient",
    "MockDataServiceClient",
    "get_data_service_client",
    "PolicyQueryTool",
    "RuleEngineTool",
    "CustomerInfoTool",
]


def create_insurance_tools(
    data_client: DataServiceClient | None = None,
) -> list:
    """创建保险工具集合（完整版）

    Args:
        data_client: 可选的 DataServiceClient 实例。
                     不传则使用全局单例（从环境变量读取配置）。
    """
    client = data_client or get_data_service_client()
    return [
        PolicyQueryTool(client=client),
        RuleEngineTool(client=client),
        CustomerInfoTool(client=client),
    ]


def create_insurance_tools_minimal(
    data_client: DataServiceClient | None = None,
) -> list:
    """创建保险工具集合（最小版，用于测试）"""
    client = data_client or get_data_service_client()
    return [
        PolicyQueryTool(client=client),
        RuleEngineTool(client=client),
    ]
