"""WithdrawalFlowEvaluator — 保险取款 4 阶段流程评估器。

阶段:
  1. identity_verify — 身份核验（customer_info, policy_query）
  2. options_query   — 方案查询（rule_engine）
  3. plan_confirm    — 方案确认，含 user_required_fields（render_a2ui）
  4. execute         — 执行取款（submit_withdrawal）

阶段数据写入方式:
  每个阶段业务完成后，LLM 调用 commit_flow_stage(stage_id=..., user_data={...})。
  框架按 field_sources 声明自动提取 tool 来源字段，LLM 仅需提供 user 来源字段。

工具名: "withdraw_money_flow_evaluator"（注册到 required_tools 时使用此名）
"""

from __future__ import annotations

from pydantic import BaseModel

from ark_agentic.core.flow.base_evaluator import (
    BaseFlowEvaluator,
    FieldSource,
    FlowEvaluatorRegistry,
    StageDefinition,
)


# ── 各阶段 Pydantic 完成条件 Schema ─────────────────────────────────────────


class IdentityVerifyOutput(BaseModel):
    """身份核验阶段完成条件"""

    user_id: str
    id_card_verified: bool          # 映射自 customer_info → identity.verified
    policy_ids: list[str]           # 映射自 policy_query → policyAssertList[*].policy_id


class OptionsQueryOutput(BaseModel):
    """方案查询阶段完成条件"""

    available_options: list[dict]   # 映射自 rule_engine → options
    total_cash_value: float         # 映射自 rule_engine → total_available_excl_loan
    max_withdrawal: float           # 映射自 rule_engine → total_available_incl_loan


class PlanConfirmOutput(BaseModel):
    """方案确认阶段完成条件（全部由用户对话提供）"""

    confirmed: bool
    selected_option: dict           # {"channels": [...], "target": <amount>}
    amount: float


class ExecuteOutput(BaseModel):
    """执行阶段完成条件（submit_withdrawal 触发外部流程后写入）"""

    submitted: bool                 # 是否已触发提交，映射自 _submitted_channels 非空
    channels: list[str]             # 已提交渠道列表，映射自 _submitted_channels


# ── WithdrawalFlowEvaluator ──────────────────────────────────────────────────


class WithdrawalFlowEvaluator(BaseFlowEvaluator):
    """保险取款 4 阶段流程评估器（业务层实现）。

    继承 BaseFlowEvaluator，仅定义阶段列表、schema 和 field_sources。
    """

    @property
    def skill_name(self) -> str:
        return "withdraw_money_flow"

    @property
    def stages(self) -> list[StageDefinition]:
        return [
            StageDefinition(
                id="identity_verify",
                name="身份核验",
                description="验证客户身份和保单信息",
                required=True,
                checkpoint=False, 
                output_schema=IdentityVerifyOutput,
                reference_file="identity_verify.md",
                tools=["customer_info", "policy_query"],
                field_sources={
                    "user_id": FieldSource(
                        source="tool",
                        state_key="_customer_info_result",
                        path="user_id",
                    ),
                    "id_card_verified": FieldSource(
                        source="tool",
                        state_key="_customer_info_result",
                        path="identity.verified",
                    ),
                    "policy_ids": FieldSource(
                        source="tool",
                        state_key="_policy_query_result",
                        transform=lambda r: [
                            p["policy_id"]
                            for p in r.get("policyAssertList", [])
                            if "policy_id" in p
                        ],
                    ),
                },
            ),
            StageDefinition(
                id="options_query",
                name="方案查询",
                description="查询可取款选项和金额",
                required=True,
                output_schema=OptionsQueryOutput,
                reference_file="options_query.md",
                tools=["rule_engine"],
                field_sources={
                    "available_options": FieldSource(
                        source="tool",
                        state_key="_rule_engine_result",
                        path="options",
                    ),
                    "total_cash_value": FieldSource(
                        source="tool",
                        state_key="_rule_engine_result",
                        path="total_available_excl_loan",
                    ),
                    "max_withdrawal": FieldSource(
                        source="tool",
                        state_key="_rule_engine_result",
                        path="total_available_incl_loan",
                    ),
                },
            ),
            StageDefinition(
                id="plan_confirm",
                name="方案确认",
                description="向用户展示方案并等待确认",
                required=True,
                checkpoint=True,   # 用户明确确认方案后持久化，断线可从执行阶段恢复
                output_schema=PlanConfirmOutput,
                reference_file="plan_confirm.md",
                tools=["render_a2ui"],
                delta_state_keys=["_plan_allocations"],  # render_a2ui 写入，resume 时还原供 submit_withdrawal 使用
                field_sources={
                    "confirmed": FieldSource(
                        source="user",
                        description="用户是否确认方案（true/false）",
                    ),
                    "selected_option": FieldSource(
                        source="user",
                        description="用户选择的方案，含 channels（渠道列表）和 target（目标金额）",
                    ),
                    "amount": FieldSource(
                        source="user",
                        description="最终确认的取款金额（元，浮点数）",
                    ),
                },
            ),
            StageDefinition(
                id="execute",
                name="执行取款",
                description="提交取款操作",
                required=True,
                output_schema=ExecuteOutput,
                reference_file="execute.md",
                tools=["submit_withdrawal"],
                field_sources={
                    "submitted": FieldSource(
                        source="tool",
                        state_key="_submitted_channels",
                        transform=lambda channels: bool(channels),
                    ),
                    "channels": FieldSource(
                        source="tool",
                        state_key="_submitted_channels",
                    ),
                },
            ),
        ]


# 全局单例，随模块 import 自动注册
withdrawal_flow_evaluator = WithdrawalFlowEvaluator()
FlowEvaluatorRegistry.register(withdrawal_flow_evaluator)
