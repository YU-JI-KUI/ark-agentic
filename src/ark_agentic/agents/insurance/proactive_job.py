"""InsuranceProactiveJob — 保险智能体的主动服务 Job

职责：
  - 定时扫描用户 memory，识别保险相关的主动提醒意图
  - 调用 policy_query 工具查询保单状态（到期日、续保、理赔等）
  - 生成主动推送通知（如"您的重疾险将于30天后到期，请及时续保"）

覆盖的典型场景：
  - 保单即将到期 → 续保提醒
  - 用户提到理赔相关 → 理赔进度跟踪
  - 保费扣款日临近 → 扣款提醒
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ark_agentic.core.jobs.proactive_service import ProactiveServiceJob
from ark_agentic.core.types import ToolCall

if TYPE_CHECKING:
    pass

# ── 意图提取 Prompt 模板 ──────────────────────────────────────────────────────
_INTENT_PROMPT_TEMPLATE = """\
今天是 {today}。

请分析以下用户记忆，判断用户是否有保险相关的主动提醒需求（如保单到期、续保、理赔进度、保费缴纳等）。

用户记忆：
{memory}

请以 JSON 格式返回，格式如下：
{{
  "intents": [
    {{
      "type": "policy_expiry",
      "title": "保单到期提醒",
      "policy_id": "保单号（如有）",
      "description": "用户的具体关注点描述"
    }}
  ]
}}

意图类型说明：
- policy_expiry     : 保单到期/续保提醒
- claim_followup    : 理赔进度跟踪
- premium_reminder  : 保费缴纳提醒
- policy_overview   : 保单整体情况查询

要求：
- 只返回用户明确表达过关注的意图
- 若无相关意图，返回 {{"intents": []}}
- policy_id 填写用户提到的保单号，若未提及则留空字符串
- 只返回 JSON，不要额外解释
"""


class InsuranceProactiveJob(ProactiveServiceJob):
    """保险智能体的主动服务 Job。

    每天定时扫描所有保险用户的 memory，找出有保单关注意图的用户，
    调用 policy_query 工具查询保单状态，主动推送提醒通知。

    使用示例（在 create_insurance_agent 中配置）：
        runner = AgentRunner(...)
        runner.set_proactive_job_class(InsuranceProactiveJob)
    """

    # ── 关键词快速过滤（无 LLM，<1ms）───────────────────────────────────────
    intent_keywords = [
        "保险", "保单", "续保", "到期", "理赔",
        "保费", "缴费", "扣款", "关注", "提醒",
        "通知我", "重疾险", "寿险", "医疗险",
    ]

    # ── Hook 1：意图提取 Prompt ──────────────────────────────────────────────

    def get_intent_prompt(self, memory: str, today: str) -> str:
        return _INTENT_PROMPT_TEMPLATE.format(memory=memory, today=today)

    # ── Hook 2：调用工具获取实时数据 ─────────────────────────────────────────

    async def fetch_data(self, intent: dict[str, Any], user_id: str) -> str:
        """调用 policy_query 工具查询保单状态。"""
        intent_type = intent.get("type", "policy_overview")
        policy_id = intent.get("policy_id", "")
        description = intent.get("description", "")

        tool = self._tool_registry.get("policy_query")
        if tool is None:
            return f"工具 policy_query 不可用，无法查询保单信息（{description}）"

        # 根据意图类型决定查询方式
        query_type = self._map_intent_to_query_type(intent_type)

        tool_call = ToolCall(
            id="proactive_policy_query",
            name="policy_query",
            arguments={
                "user_id": user_id,
                "query_type": query_type,
                **({"policy_id": policy_id} if policy_id else {}),
            },
        )

        try:
            result = await tool.execute(tool_call, context=None)
            if result.is_error:
                return f"查询保单时发生错误：{result.error}"

            return self._format_policy_result(intent_type, result.data)
        except Exception as e:
            return f"查询保单失败：{e}"

    # ── 内部辅助 ─────────────────────────────────────────────────────────────

    @staticmethod
    def _map_intent_to_query_type(intent_type: str) -> str:
        """将意图类型映射到 policy_query 工具支持的查询类型。

        policy_query 支持的 query_type 枚举：
          list              — 保单列表（到期提醒、保费缴纳、全览等场景）
          detail            — 保单详情（需要 policy_id）
          cash_value        — 现金价值（需要 policy_id）
          withdrawal_limit  — 可取款额度（需要 policy_id）
        """
        mapping = {
            "policy_expiry":    "list",    # 到期提醒 → 先拉列表找到期保单
            "claim_followup":   "list",    # 理赔跟进 → 先拉列表找相关保单
            "premium_reminder": "list",    # 保费缴纳提醒 → 拉列表看缴费状态
            "policy_overview":  "list",    # 整体保单查询 → 拉完整列表
        }
        return mapping.get(intent_type, "list")

    @staticmethod
    def _format_policy_result(data: Any) -> str:
        """将 policy_query 返回的结构化数据转换为可读摘要。"""
        if not data:
            return "未查询到相关保单信息"

        if isinstance(data, dict):
            policies = data.get("policies") or data.get("items") or []
            if not policies and isinstance(data, dict):
                # 单条保单
                policies = [data]
        elif isinstance(data, list):
            policies = data
        else:
            return str(data)

        if not policies:
            return "当前无有效保单记录"

        summaries = []
        for policy in policies[:3]:  # 最多展示3条，避免通知过长
            if not isinstance(policy, dict):
                continue
            name = policy.get("product_name") or policy.get("name", "未知险种")
            status = policy.get("status", "")
            expire_date = policy.get("expire_date") or policy.get("end_date", "")

            line = f"【{name}】"
            if status:
                line += f" 状态：{status}"
            if expire_date:
                line += f" 到期：{expire_date}"
            summaries.append(line)

        if not summaries:
            return "保单数据格式异常，请登录 App 查看"

        return "\n".join(summaries)
