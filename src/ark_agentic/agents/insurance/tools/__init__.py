"""
保险业务工具

提供保险场景相关的工具实现。

工具列表：
- PolicyQueryTool: 保单查询（列表、详情、现金价值、可取款额度）
- RuleEngineTool: 规则引擎（计算取款方案、比较方案）
- CustomerInfoTool: 客户信息（身份、联系方式、受益人、交易历史）
- RenderA2UITool: 统一 A2UI 渲染（blocks 动态组合 / card_type 模板加载）
- CollectUserFieldsTool: 向当前流程阶段提交用户收集的字段（Flow 专用）
- RollbackFlowStageTool: 回退到指定 checkpoint 阶段（Flow 专用）
"""

from pathlib import Path

from ark_agentic.core.a2ui import A2UITheme
from ark_agentic.core.tools import BlocksConfig, RenderA2UITool, TemplateConfig

from ..a2ui import create_insurance_blocks, create_insurance_components
from ..a2ui.template_extractors import (
    policy_detail_extractor,
    withdraw_plan_extractor,
    withdraw_summary_extractor,
)
from .data_service import DataServiceClient, MockDataServiceClient, get_data_service_client
from .policy_query import PolicyQueryTool
from .rule_engine import RuleEngineTool
from .customer_info import CustomerInfoTool
from .submit_withdrawal import SubmitWithdrawalTool
from .flow_evaluator import withdrawal_flow_evaluator
from ark_agentic.core.flow.collect_user_fields import CollectUserFieldsTool
from ark_agentic.core.flow.rollback_flow_stage import RollbackFlowStageTool

_A2UI_TEMPLATE_ROOT = Path(__file__).resolve().parent.parent / "a2ui" / "templates"
_CARD_EXTRACTORS = {
    "withdraw_summary": withdraw_summary_extractor,
    "withdraw_plan": withdraw_plan_extractor,
    "policy_detail": policy_detail_extractor,
}


INSURANCE_THEME = A2UITheme(
    root_gap=16,
    root_padding=[16, 32, 16, 16],
    section_gap=12,
    header_gap=8,
    card_padding=16,
)

_THEMED_BLOCKS = create_insurance_blocks(INSURANCE_THEME)
_THEMED_COMPONENTS = create_insurance_components(INSURANCE_THEME)

_INSURANCE_STATE_KEYS = (
    "_rule_engine_result",
    "_policy_query_result",
    "_customer_info_result",
)


def _create_render_a2ui_tool() -> RenderA2UITool:
    return RenderA2UITool(
        blocks=BlocksConfig(
            agent_blocks=_THEMED_BLOCKS,
            agent_components=_THEMED_COMPONENTS,
            theme=INSURANCE_THEME,
        ),
        template=TemplateConfig(
            template_root=_A2UI_TEMPLATE_ROOT,
            extractors=_CARD_EXTRACTORS,
        ),
        group="insurance",
        state_keys=_INSURANCE_STATE_KEYS,
    )


__all__ = [
    "DataServiceClient",
    "MockDataServiceClient",
    "get_data_service_client",
    "PolicyQueryTool",
    "RuleEngineTool",
    "CustomerInfoTool",
    "RenderA2UITool",
    "SubmitWithdrawalTool",
    "CollectUserFieldsTool",
    "withdrawal_flow_evaluator",
    "create_insurance_tools",
    "create_insurance_tools_minimal",
]


def create_insurance_tools(
    data_client: DataServiceClient | None = None,
    *,
    sessions_dir: "str | Path | None" = None,
) -> list:
    """创建保险工具集合（完整版）"""
    from ark_agentic.core.tools.resume_task import ResumeTaskTool

    client = data_client or get_data_service_client()

    return [
        PolicyQueryTool(client=client),
        RuleEngineTool(client=client),
        CustomerInfoTool(client=client),
        _create_render_a2ui_tool(),
        SubmitWithdrawalTool(),
        CollectUserFieldsTool(),
        RollbackFlowStageTool(),
        ResumeTaskTool(sessions_dir=sessions_dir or "data/ark_sessions/insurance"),
    ]


def create_insurance_tools_minimal(
    data_client: DataServiceClient | None = None,
) -> list:
    """创建保险工具集合（最小版，用于测试）"""
    client = data_client or get_data_service_client()
    return [
        PolicyQueryTool(client=client),
        RuleEngineTool(client=client),
        _create_render_a2ui_tool(),
    ]
