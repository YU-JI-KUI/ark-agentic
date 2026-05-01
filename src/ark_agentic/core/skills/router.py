"""Skill 路由器 — Protocol、数据契约与 NullSkillRouter。

Dynamic 模式下，AgentRunner 在 ReAct 循环开始前会调用 SkillRouter.route()，
将路由结果写入 session.state["_active_skill_id"]，与 read_skill 工具同槽位。
模型在 ReAct 中仍可通过 read_skill 覆盖路由决定。

Spec: docs/superpowers/specs/2026-04-27-dynamic-skill-router-design.md
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Callable, Protocol, runtime_checkable

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from ..types import (
    AgentMessage,
    MessageRole,
    SkillEntry,
)

logger = logging.getLogger(__name__)


@dataclass
class RouteContext:
    """Router 输入上下文。

    Fields:
      user_input: 当前轮 user 消息内容
      history: session.messages[-N:] 切片，含 user / assistant / tool 三种 role
      current_active_skill_id: 上轮 active（含 read_skill 工具写入的）；None 表示未激活
      candidate_skills: 已通过 should_include / eligibility 过滤的 SkillEntry 列表
    """
    user_input: str
    history: list[AgentMessage]
    current_active_skill_id: str | None
    candidate_skills: list[SkillEntry]


@dataclass
class RouteDecision:
    """Router 输出决策。

    skill_id: 选定的 skill id；None 表示不激活任何 skill
    reason: 仅用于 log / OTel，不入 system prompt
    """
    skill_id: str | None
    reason: str = ""


@runtime_checkable
class SkillRouter(Protocol):
    """Skill 路由器契约。

    实现需要保证：
      - route() 不抛异常（错误时返回 RouteDecision，runner 仅作为 Protocol 违约的兜底）
      - timeout 由实现内部用 asyncio.wait_for 强制（runner 不再外层包裹）
    """
    history_window: int
    timeout: float

    async def route(self, ctx: RouteContext) -> RouteDecision: ...


# ── LLMSkillRouter ────────────────────────────────────────────────────────


_SYSTEM_PROMPT = """你是一个 skill 路由器。根据用户对话上下文，从可用 skill 列表中选择最匹配的一个。
仅输出严格 JSON：{"skill_id": "<id 或 null>", "reason": "<≤30字>"}，不要包含其它文本。"""


def _render_history_line(msg: AgentMessage) -> str:
    """将单条 AgentMessage 渲染为单行字符串供 router prompt 使用。"""
    if msg.role == MessageRole.USER:
        return f"user: {msg.content or ''}"
    if msg.role == MessageRole.ASSISTANT:
        if msg.content:
            return f"assistant: {msg.content}"
        if msg.tool_calls:
            names = ", ".join(tc.name for tc in msg.tool_calls)
            return f"assistant: [calling tools: {names}]"
        return "assistant: "
    if msg.role == MessageRole.TOOL and msg.tool_results:
        return "\n".join(f"tool: {tr.llm_digest}" for tr in msg.tool_results)
    return ""


class LLMSkillRouter:
    """LLM-based default SkillRouter.

    实现内部用 asyncio.wait_for 自管 timeout，所有错误内部吸收返回 RouteDecision，
    runner 端仅作为 Protocol 违约的兜底（捕异常即可）。
    """

    def __init__(
        self,
        llm_factory: Callable[[], BaseChatModel],
        history_window: int = 6,
        timeout: float = 5.0,
    ) -> None:
        self._llm_factory = llm_factory
        self.history_window = history_window
        self.timeout = timeout

    async def route(self, ctx: RouteContext) -> RouteDecision:
        # 防御性：候选为空时短路，不调 LLM
        if not ctx.candidate_skills:
            return RouteDecision(skill_id=None, reason="no_candidates")

        prompt = self._build_user_prompt(ctx)
        llm = self._llm_factory()
        try:
            response = await asyncio.wait_for(
                llm.ainvoke([
                    SystemMessage(content=_SYSTEM_PROMPT),
                    HumanMessage(content=prompt),
                ]),
                timeout=self.timeout,
            )
        except asyncio.TimeoutError:
            logger.warning("Skill router LLM call timed out after %ss", self.timeout)
            return RouteDecision(
                skill_id=ctx.current_active_skill_id, reason="timeout",
            )
        except Exception as exc:
            logger.warning("Skill router LLM call failed: %s", exc, exc_info=True)
            return RouteDecision(
                skill_id=ctx.current_active_skill_id,
                reason=type(exc).__name__,
            )

        return self._parse_decision(response.content, ctx)

    def _build_user_prompt(self, ctx: RouteContext) -> str:
        history_window = (
            ctx.history[-self.history_window:] if self.history_window else []
        )

        skills_section = "\n".join(
            f"  - id: {s.id}\n    description: {s.metadata.description}"
            for s in ctx.candidate_skills
        )
        history_lines: list[str] = []
        for msg in history_window:
            line = _render_history_line(msg)
            if line:
                history_lines.append(line)
        history_section = "\n".join(history_lines) or "(empty)"
        current = ctx.current_active_skill_id or "none"

        return (
            "<task>从可用 skill 列表中为用户当前输入选择最匹配的一个，或返回 null。</task>\n\n"
            f"<available_skills>\n{skills_section}\n</available_skills>\n\n"
            f"<conversation_history>\n{history_section}\n</conversation_history>\n\n"
            f"<current_active_skill>{current}</current_active_skill>\n\n"
            f"<latest_user_input>{ctx.user_input}</latest_user_input>\n\n"
            "<rules>\n"
            "1. 用户输入若是省略主语的追问 / 延续同主题，保持 current_active_skill。\n"
            "2. 用户明显切换主题，选最匹配的新 skill。\n"
            "3. 输入若是寒暄 / 闲聊 / 与所有 skill 无关，返回 null。\n"
            "4. 当前已激活的 skill 优先尊重，除非有明确切换信号。\n"
            "</rules>\n\n"
            "<output_format>严格 JSON: {\"skill_id\": \"<id 或 null>\", \"reason\": \"<≤30字>\"}</output_format>"
        )

    def _parse_decision(
        self, raw: str | list, ctx: RouteContext,
    ) -> RouteDecision:
        text = raw if isinstance(raw, str) else str(raw)
        text = text.strip()
        # 容忍 ```json ... ``` fenced 输出
        if text.startswith("```"):
            lines = text.splitlines()
            text = "\n".join(
                ln for ln in lines if not ln.strip().startswith("```")
            ).strip()
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("Skill router returned non-JSON: %r", text[:200])
            return RouteDecision(
                skill_id=ctx.current_active_skill_id, reason="parse_error",
            )

        if not isinstance(data, dict):
            return RouteDecision(
                skill_id=ctx.current_active_skill_id, reason="not_an_object",
            )

        skill_id = data.get("skill_id")
        reason = str(data.get("reason") or "")[:80]

        if skill_id is None:
            return RouteDecision(skill_id=None, reason=reason)

        if not isinstance(skill_id, str):
            return RouteDecision(
                skill_id=ctx.current_active_skill_id, reason="invalid_id_type",
            )

        candidate_ids = {s.id for s in ctx.candidate_skills}
        if skill_id not in candidate_ids:
            logger.warning(
                "Skill router returned id not in candidates: %s (candidates=%s)",
                skill_id, sorted(candidate_ids),
            )
            return RouteDecision(skill_id=None, reason="invalid_id")

        return RouteDecision(skill_id=skill_id, reason=reason)
