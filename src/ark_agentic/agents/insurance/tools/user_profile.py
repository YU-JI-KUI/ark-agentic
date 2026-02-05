"""
用户画像工具

查询和分析用户画像信息。
"""

from __future__ import annotations

from typing import Any

from ark_agentic.core.tools.base import (
    AgentTool,
    ToolParameter,
    read_string_param_required,
)
from ark_agentic.core.types import AgentToolResult, ToolCall


class UserProfileTool(AgentTool):
    """用户画像工具

    查询用户的画像信息，用于个性化推荐。
    """

    name = "user_profile"
    description = "查询用户画像信息，包括基本信息、风险偏好、历史行为等"
    group = "insurance"

    parameters = [
        ToolParameter(
            name="user_id",
            type="string",
            description="用户ID",
            required=True,
        ),
        ToolParameter(
            name="profile_type",
            type="string",
            description="画像类型",
            required=False,
            enum=["basic", "risk_preference", "behavior", "full"],
            default="full",
        ),
    ]

    async def execute(
        self, tool_call: ToolCall, context: dict[str, Any] | None = None
    ) -> AgentToolResult:
        """执行用户画像查询"""
        args = tool_call.arguments
        user_id = read_string_param_required(args, "user_id")
        # profile_type = read_string_param(args, "profile_type", "full")

        # 模拟查询
        result = self._get_user_profile(user_id)

        return AgentToolResult.json_result(tool_call.id, result)

    def _get_user_profile(self, user_id: str) -> dict[str, Any]:
        """获取用户画像（模拟数据）"""
        return {
            "user_id": user_id,
            "basic": {
                "name": "张先生",
                "age": 42,
                "gender": "male",
                "occupation": "企业管理",
                "income_level": "high",
                "family_status": "已婚有子女",
            },
            "risk_preference": {
                "level": "moderate",  # conservative, moderate, aggressive
                "description": "稳健型",
                "preferred_term": "medium",  # short, medium, long
            },
            "insurance_profile": {
                "customer_years": 5,
                "total_policies": 2,
                "total_premium": 62000,
                "claim_history": [],
                "service_interactions": 12,
            },
            "behavior": {
                "app_usage_frequency": "monthly",
                "preferred_channel": "app",
                "response_time_preference": "quick",
                "communication_style": "concise",
            },
            "tags": [
                "高净值客户",
                "活跃用户",
                "有取款历史",
            ],
            "recommendations": {
                "communication_tips": [
                    "偏好简洁直接的沟通方式",
                    "关注投资收益和灵活性",
                    "对保障功能也有需求",
                ],
                "product_interests": [
                    "年金险",
                    "投资型保险",
                ],
            },
        }
