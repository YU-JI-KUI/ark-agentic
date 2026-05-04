"""WithdrawalFlowEvaluator — 保险取款 5 阶段流程评估器。

阶段:
  1. identity_verify — 身份核验（customer_info, policy_query）
  2. options_query   — 方案查询（rule_engine）
  3. plan_confirm    — 方案确认，含 user_required_fields（render_a2ui + collect_user_fields）
  4. double_confirm  — 二次确认，收集 double_confirm:bool（collect_user_fields）
  5. execute         — 执行取款（submit_withdrawal，全工具字段，自动提交）

评估器不再是 LLM 工具，由 FlowCallbacks 的 before_model_flow_eval Hook 自动驱动：
  - 评估当前阶段并注入结构化提示词，列出待收集字段
  - evaluate() 内部统一完成字段抽取、校验、自动提交
"""

from __future__ import annotations

from pydantic import BaseModel

from ark_agentic.core.flow.base_evaluator import (
    BaseFlowEvaluator,
    FieldDefinition,
    StageDefinition,
)


# ── 各阶段 Pydantic 完成条件 Schema ─────────────────────────────────────────


class IdentityVerifyOutput(BaseModel):
    """身份核验阶段完成条件"""

    user_id: str
    phone: str                      # 映射自 contact , 必填字段
    email: str | None               # 映射自 contact , 非必填字段
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


class DoubleConfirmOutput(BaseModel):
    """二次确认阶段完成条件（全部由用户对话提供）"""

    double_confirm: bool            # 用户再次明确确认，防误触


class ExecuteOutput(BaseModel):
    """执行阶段完成条件（submit_withdrawal 触发外部流程后自动写入）"""

    submitted: bool                 # 是否已触发提交，映射自 _submitted_channels 非空
    channels: list[str]             # 已提交渠道列表，映射自 _submitted_channels


# ── WithdrawalFlowEvaluator ──────────────────────────────────────────────────


class WithdrawalFlowEvaluator(BaseFlowEvaluator):
    """保险取款 4 阶段流程评估器（业务层实现）。

    继承 BaseFlowEvaluator，仅定义阶段列表、schema 和 fields。
    """

    @property
    def skill_name(self) -> str:
        return "withdraw_money_flow"

    @property
    def task_name_template(self) -> str:
        # amount 来自 stage_plan_confirm.amount（PlanConfirmOutput，float）；
        # :.0f 让整数金额显示为 "2000" 而非 "2000.0"。
        # 方案确认前渲染为 "资金领取（{待定}元）任务"，确认后刷新为具体金额。
        return "资金领取（{amount:.0f}元）任务"

    @property
    def stages(self) -> list[StageDefinition]:
        return [
            StageDefinition(
                id="identity_verify",
                name="身份核验",
                description="验证客户身份和保单信息",
                checkpoint=False,
                output_schema=IdentityVerifyOutput,
                reference_file="identity_verify.md",
                tools=["customer_info", "policy_query"],
                fields={
                    "user_id": FieldDefinition(
                        state_key="_customer_info_result",
                        path="identity.id_number",
                    ),
                    "phone": FieldDefinition(
                        state_key="_customer_info_result",
                        path="contact.phone_number",
                    ),
                    "email": FieldDefinition(
                        state_key="_customer_info_result",
                        path="contact.email",
                    ),                    
                    "id_card_verified": FieldDefinition(
                        state_key="_customer_info_result",
                        path="identity.verified",
                    ),
                    "policy_ids": FieldDefinition(
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
                output_schema=OptionsQueryOutput,
                reference_file="options_query.md",
                tools=["rule_engine"],
                fields={
                    "available_options": FieldDefinition(
                        state_key="_rule_engine_result",
                        path="options",
                    ),
                    "total_cash_value": FieldDefinition(
                        state_key="_rule_engine_result",
                        path="total_available_excl_loan",
                    ),
                    "max_withdrawal": FieldDefinition(
                        state_key="_rule_engine_result",
                        path="total_available_incl_loan",
                    ),
                },
            ),
            StageDefinition(
                id="plan_confirm",
                name="方案确认",
                description="向用户展示方案并等待确认",
                checkpoint=True,   # 用户明确确认方案后持久化，断线可从执行阶段恢复
                output_schema=PlanConfirmOutput,
                reference_file="plan_confirm.md",
                tools=["render_a2ui"],
                delta_state_keys=["_plan_allocations"],  # render_a2ui 写入，resume 时还原供 submit_withdrawal 使用
                fields={
                    "confirmed": FieldDefinition(
                        description="用户是否确认方案（true/false）",
                    ),
                    "selected_option": FieldDefinition(
                        description="用户选择的方案，含 channels（渠道列表）和 target（目标金额）",
                    ),
                    "amount": FieldDefinition(
                        description="最终确认的取款金额（元，浮点数）",
                    ),
                },
            ),
            StageDefinition(
                id="double_confirm",
                name="二次确认",
                description="向用户展示最终取款摘要，要求再次明确确认后方可执行",
                output_schema=DoubleConfirmOutput,
                reference_file="double_confirm.md",
                tools=[],
                fields={
                    "double_confirm": FieldDefinition(
                        description="用户是否再次确认办理（true/false）",
                    ),
                },
            ),
            StageDefinition(
                id="execute",
                name="执行取款",
                description="提交取款操作",
                output_schema=ExecuteOutput,
                reference_file="execute.md",
                tools=["submit_withdrawal"],
                fields={
                    "submitted": FieldDefinition(
                        state_key="_submitted_channels",
                        transform=lambda channels: bool(channels),
                    ),
                    "channels": FieldDefinition(
                        state_key="_submitted_channels",
                    ),
                },
            ),
        ]


# 全局单例；注册由 agent factory 显式完成（见 agents/insurance/agent.py），
# 以保证调用方明确控制注入的 namespace 并消除 import side effect。
withdrawal_flow_evaluator = WithdrawalFlowEvaluator()
