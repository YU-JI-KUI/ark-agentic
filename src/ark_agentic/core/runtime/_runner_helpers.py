"""Stateless helpers extracted from ``BaseAgent``.

These are all pure transformations on session / tool-result / event data
— moved out of the BaseAgent class to keep the agent module focused on
identity + orchestration. None of them touch ``self``; they take only
the values they operate on.
"""

from __future__ import annotations

import logging
import warnings
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any, TYPE_CHECKING

from ..llm.errors import LLMError, LLMErrorReason
from ..stream.event_bus import AgentEventHandler
from ..types import AgentMessage, AgentToolResult, SessionEntry

if TYPE_CHECKING:
    from .callbacks import CallbackEvent

logger = logging.getLogger(__name__)


def augment_user_metadata(
    msg: AgentMessage,
    chat_request: dict[str, Any] | None,
) -> None:
    """Display-only metadata for the Studio user-message panel.

    Only ``chat_request`` lives here; trace correlation is observability
    cross-cut surfaced via the assistant message's ``trace.trace_id`` link.
    """
    if chat_request:
        msg.metadata["chat_request"] = chat_request


def apply_state_delta(state: dict[str, Any], delta: dict[str, Any]) -> None:
    """Dot-path-aware deep merge into ``session.state``.

    Plain key → ``state[key] = value`` (shallow overwrite).
    Dotted key (e.g. ``"_flow_context.stage_identity_verify"``) → walk down
    creating dicts as needed, set leaf. Avoids replacing the parent object,
    so sibling keys at the same depth are preserved.
    """
    for key, value in delta.items():
        if "." in key:
            parts = key.split(".")
            obj = state
            for part in parts[:-1]:
                if not isinstance(obj.get(part), dict):
                    obj[part] = {}
                obj = obj[part]
            obj[parts[-1]] = value
        else:
            state[key] = value


def merge_tool_state_deltas(
    session: SessionEntry,
    tool_results: list[AgentToolResult],
) -> None:
    """Apply each tool's ``state_delta`` (typed or metadata-borne) to session.state."""
    for tr in tool_results:
        state_delta = (
            tr.state_delta
            if tr.state_delta is not None
            else tr.metadata.get("state_delta")
        )
        if state_delta and isinstance(state_delta, dict):
            apply_state_delta(session.state, state_delta)
            session.updated_at = datetime.now()


def apply_session_effects(
    session: SessionEntry,
    tool_results: list[AgentToolResult],
) -> None:
    """Dispatch typed ``session_effects`` from tool results to ``SessionEntry`` mutations.

    Parallel to ``merge_tool_state_deltas``: state_delta channel handles
    generic ``session.state`` dict mutations; session_effects channel handles
    typed ``SessionEntry`` field mutations (e.g. ``active_skill_ids``).
    Malformed effects log a warning and are skipped — defensive against the
    tool path so one bad effect can't abort a turn.
    """
    from pydantic import ValidationError

    from ..types import SessionEffect

    for tr in tool_results:
        effects = (
            tr.session_effects
            if tr.session_effects is not None
            else tr.metadata.get("session_effects", [])
        )
        if not isinstance(effects, list):
            continue
        for raw in effects:
            try:
                effect = SessionEffect.model_validate(raw)
            except ValidationError as exc:
                logger.warning("invalid session_effect %r: %s", raw, exc)
                continue
            if effect.op == "activate_skill":
                session.set_active_skill_ids(effect.skill_ids)


def merge_input_context(
    session: SessionEntry, input_context: dict[str, Any]
) -> None:
    """Merge ``input_context`` into ``session.state`` (always overwrite)."""
    for k, v in input_context.items():
        session.state[k] = v


_USER_FRIENDLY_ERROR_MESSAGES: dict[LLMErrorReason, str] = {
    LLMErrorReason.AUTH:
        "抱歉，模型认证失败，请检查 API 配置。如需帮助，请联系技术支持。",
    LLMErrorReason.QUOTA:
        "抱歉，当前 API 账户余额不足，服务暂时不可用，请联系技术支持充值后重试。",
    LLMErrorReason.RATE_LIMIT:
        "抱歉，当前请求较多，请稍后再试。",
    LLMErrorReason.TIMEOUT:
        "抱歉，请求超时，请检查网络连接后重试。",
    LLMErrorReason.CONTEXT_OVERFLOW:
        "抱歉，对话内容过长，系统将自动压缩历史消息后重试。如问题持续，请新建会话。",
    LLMErrorReason.CONTENT_FILTER:
        "抱歉，您的输入包含不适当内容，请修改后重试。",
    LLMErrorReason.SERVER_ERROR:
        "抱歉，服务暂时不可用，请稍后重试。",
    LLMErrorReason.NETWORK:
        "抱歉，网络连接出现问题，请检查网络后重试。",
}


def user_friendly_error_message(error: LLMError) -> str:
    """Return the user-facing message for an ``LLMError``."""
    return _USER_FRIENDLY_ERROR_MESSAGES.get(
        error.reason,
        "抱歉，处理您的请求时出现了问题，请稍后重试。",
    )


def dispatch_event(
    handler: AgentEventHandler, event: "CallbackEvent",
) -> None:
    """Route ``CallbackEvent`` to the appropriate ``AgentEventHandler`` method."""
    if event.type == "step":
        handler.on_step(event.data.get("text", ""))
    elif event.type == "ui_component":
        handler.on_ui_component(event.data)
    else:
        handler.on_custom_event(event.type, event.data)


def enrich_skills_with_stage_reference(
    skills: list, current_stage_id: str,
) -> list:
    """Inject stage-specific reference content into matching ``SkillEntry.content``.

    Looks up the registered ``FlowEvaluator`` (by skill id, full or short),
    reads the active stage's ``reference_file``, and appends its body.
    Missing files emit a warning but don't abort the turn.
    """
    from ..flow.base_evaluator import FlowEvaluatorRegistry

    enriched = []
    for skill in skills:
        skill_short = skill.id.split(".")[-1]
        evaluator = (
            FlowEvaluatorRegistry.get(skill.id)
            or FlowEvaluatorRegistry.get(skill_short)
        )

        ref_filename: str | None = None
        if evaluator:
            stage_def = next(
                (s for s in evaluator.stages if s.id == current_stage_id), None,
            )
            ref_filename = stage_def.reference_file if stage_def else None

        if ref_filename:
            ref_path = Path(skill.path) / "references" / ref_filename
            if ref_path.exists():
                ref_content = ref_path.read_text(encoding="utf-8")
                enriched.append(replace(
                    skill,
                    content=(
                        skill.content
                        + f"\n\n---\n### 当前阶段参考: {current_stage_id}\n\n"
                        + ref_content
                    ),
                ))
                continue
            warnings.warn(
                f"[FlowEvaluator] reference file not found: {ref_path}",
                stacklevel=4,
            )
        enriched.append(skill)
    return enriched
