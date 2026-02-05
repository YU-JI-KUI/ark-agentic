"""
保险业务工具

提供保险场景相关的工具实现。

工具列表：
- PolicyQueryTool: 保单查询（列表、详情、现金价值、可取款额度）
- RuleEngineTool: 规则引擎（计算取款方案、比较方案）
- UserProfileTool: 用户画像（基本信息、风险偏好、行为特征）
- CustomerInfoTool: 客户信息（身份、联系方式、受益人、交易历史）
- IdentityVerificationTool: 身份验证（短信、人脸、密码）
"""

from .policy_query import PolicyQueryTool
from .rule_engine import RuleEngineTool
from .user_profile import UserProfileTool
from .customer_info import CustomerInfoTool, IdentityVerificationTool

__all__ = [
    "PolicyQueryTool",
    "RuleEngineTool",
    "UserProfileTool",
    "CustomerInfoTool",
    "IdentityVerificationTool",
]


def create_insurance_tools() -> list:
    """创建保险工具集合（完整版）"""
    return [
        PolicyQueryTool(),
        RuleEngineTool(),
        UserProfileTool(),
        CustomerInfoTool(),
        IdentityVerificationTool(),
    ]


def create_insurance_tools_minimal() -> list:
    """创建保险工具集合（最小版，用于测试）"""
    return [
        PolicyQueryTool(),
        RuleEngineTool(),
        UserProfileTool(),
    ]
