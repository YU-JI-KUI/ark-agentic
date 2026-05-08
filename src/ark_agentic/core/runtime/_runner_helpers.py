"""Stateless helpers extracted from ``BaseAgent``.

Moved out of the BaseAgent class to keep the agent module focused on
identity + orchestration. Most are pure transformations; a few touch
mutable arguments (e.g. ``apply_state_delta`` mutates the session-state
dict; ``run_hooks`` invokes async callables) but none take ``self`` —
they operate only on the arguments they receive.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, TYPE_CHECKING

from ..llm.errors import LLMError, LLMErrorReason
from ..llm.sampling import SamplingConfig
from ..stream.event_bus import AgentEventHandler
from ..types import (
    AgentMessage,
    AgentToolResult,
    MessageRole,
    RunOptions,
    SessionEntry,
)

if TYPE_CHECKING:
    from ..skills.loader import SkillLoader
    from ..tools.base import AgentTool
    from ..tools.registry import ToolRegistry
    from ..types import SkillLoadMode
    from ._runner_types import _RunParams, RunnerConfig
    from .callbacks import CallbackContext, CallbackEvent, CallbackResult

logger = logging.getLogger(__name__)


def augment_user_metadata(
    msg: AgentMessage,
    chat_request: dict[str, Any] | None,
) -> None:
    """Display-only metadata for the Studio user-message panel.

    Stamps ``chat_request`` (caller-supplied) and ``trace.trace_id`` from
    the active OTel span. The user message is persisted from inside the
    ``agent.run`` span, so capturing the trace_id here lets the Studio
    "View in trace" button work on user turns too — without it, only
    assistant turns can deep-link.
    """
    from ..observability import current_trace_id_or_none

    if chat_request:
        msg.metadata["chat_request"] = chat_request
    trace_id = current_trace_id_or_none()
    if trace_id:
        msg.metadata.setdefault("trace", {})["trace_id"] = trace_id


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
    elif event.type == "citation_batch":
        for span in event.data.get("spans", []):
            handler.on_citation(span)
        handler.on_citation_list(event.data.get("entries", []))
    else:
        handler.on_custom_event(event.type, event.data)


def resolve_run_params(
    config: "RunnerConfig", run_options: RunOptions | None,
) -> "_RunParams":
    """Compute (model, sampling_override, skill_load_mode) for one run.

    Pure: combines static ``RunnerConfig`` with per-call ``RunOptions``
    overrides. ``temperature`` override produces a derived
    ``SamplingConfig`` via ``model_copy``.
    """
    from ._runner_types import _RunParams  # local import: avoid cycle

    model = (run_options.model if run_options else None) or config.model
    sampling_override: SamplingConfig | None = None
    if run_options and run_options.temperature is not None:
        sampling_override = config.sampling.model_copy(
            update={"temperature": run_options.temperature}
        )
    return _RunParams(
        model=model,
        sampling_override=sampling_override,
        skill_load_mode=config.skill_config.load_mode.value,
    )


async def run_hooks(
    hooks: list,
    cb_ctx: "CallbackContext | None",
    *,
    context: dict[str, Any] | None = None,
    handler: AgentEventHandler | None = None,
    **kwargs: Any,
) -> "CallbackResult | None":
    """Run callback hooks in order, applying ``context_updates`` and dispatching
    events on each non-``None`` result.

    Returns the first result whose action is not ``PASS`` (subsequent hooks
    skipped) or the last non-``None`` result, whichever comes first.
    """
    from .callbacks import HookAction  # local import: avoid cycle

    if not hooks or cb_ctx is None:
        return None
    last: "CallbackResult | None" = None
    for cb in hooks:
        r = await cb(cb_ctx, **kwargs)
        if r is None:
            continue
        if r.context_updates and context is not None:
            context.update(r.context_updates)
        if r.event and handler:
            dispatch_event(handler, r.event)
        last = r
        if r.action != HookAction.PASS:
            return r
    return last


def serialize_messages_for_llm(
    session: SessionEntry, system_prompt: str,
) -> list[dict[str, Any]]:
    """Convert ``session.messages`` into the OpenAI-compatible message list.

    Caller supplies the already-built ``system_prompt`` so this stays a
    pure transformation over ``session`` content. Skips ``SYSTEM`` messages
    in history (the supplied prompt is the SSOT).
    """
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt}
    ]
    for msg in session.messages:
        if msg.role == MessageRole.SYSTEM:
            continue
        if msg.role == MessageRole.USER:
            messages.append({"role": "user", "content": msg.content})
        elif msg.role == MessageRole.ASSISTANT:
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": msg.content or "",
            }
            if msg.tool_calls:
                assistant_msg["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                        },
                    }
                    for tc in msg.tool_calls
                ]
            messages.append(assistant_msg)
        elif msg.role == MessageRole.TOOL:
            if msg.tool_results:
                for tr in msg.tool_results:
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tr.tool_call_id,
                        "content": tr.llm_digest,
                    })
    return messages


def filter_visible_tools(
    tool_registry: "ToolRegistry",
    skill_loader: "SkillLoader | None",
    skill_load_mode: "SkillLoadMode",
    session: SessionEntry | None,
) -> list["AgentTool"]:
    """Skill-aware tool visibility filter (single source of truth).

    full mode: every registered tool is visible.
    dynamic mode: ``visibility="always"`` tools are always visible; the
    rest are gated on the session's active skill — only tools listed in
    ``skill.metadata.required_tools`` come through.
    """
    from ..types import SkillLoadMode as _SkillLoadMode  # local: type narrowing

    all_tools = tool_registry.list_all()

    if not skill_loader or skill_load_mode == _SkillLoadMode.full:
        return all_tools

    always = [t for t in all_tools if getattr(t, "visibility", "auto") == "always"]
    active_skill_id = session.current_active_skill_id if session else None
    if not active_skill_id:
        return always

    skill = skill_loader.get_skill(active_skill_id)
    allowed = set(skill.metadata.required_tools or []) if skill else set()
    seen = {t.name for t in always}
    skill_tools = [t for t in all_tools if t.name in allowed and t.name not in seen]
    return always + skill_tools
