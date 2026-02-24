"""
输出格式化器

将 AG-UI 原生 AgentStreamEvent 适配到不同的传输协议格式。
底层一套实现，展示层做区分。

协议:
  - agui:       裸 AG-UI 事件（原生输出）
  - enterprise: 企业 AGUI 信封（AGUIEnvelope 包装）
  - internal:   旧版 response.* 格式（向后兼容）
  - alone:      旧版 ALONE 协议（sa_* 事件）
"""

from __future__ import annotations

import json
from typing import Any, Protocol

from .agui_models import AGUIDataPayload, AGUIEnvelope
from .events import AgentStreamEvent


class OutputFormatter(Protocol):
    """输出格式化协议（DIP 扩展点）。"""

    def format(self, event: AgentStreamEvent) -> str | None:
        """将 AG-UI 事件格式化为 SSE 字符串。返回 None 表示跳过该事件。"""
        ...


# ============ Bare AG-UI ============


class BareAGUIFormatter:
    """直接输出 AG-UI 原生事件，不加包装。"""

    def format(self, event: AgentStreamEvent) -> str:
        data = event.model_dump_json(exclude_none=True)
        return f"event: {event.type}\ndata: {data}\n\n"


# ============ Legacy Internal (response.*) ============

_AGUI_TO_INTERNAL: dict[str, str] = {
    "run_started": "response.created",
    "step_started": "response.step",
    "step_finished": "response.step.done",     # distinct: closes current step
    "text_message_content": "response.content.delta",
    "tool_call_start": "response.tool_call.start",
    "tool_call_result": "response.tool_call.result",
    "custom": "response.ui.component",
    "run_finished": "response.completed",
    "run_error": "response.failed",
}

_SKIP_INTERNAL = {
    "text_message_start",
    "text_message_end",
    "tool_call_args",
    "tool_call_end",
    "state_snapshot",
    "state_delta",
    "messages_snapshot",
    "raw",
}


class LegacyInternalFormatter:
    """将 AG-UI 事件映射回旧版 response.* 事件格式。

    供现有 index.html 前端无缝兼容使用。
    step_finished → response.step.done（前端 EVENT_ALIASES 对应同名 case）。
    """

    def format(self, event: AgentStreamEvent) -> str | None:
        if event.type in _SKIP_INTERNAL:
            return None

        if event.type == "text_message_content" and getattr(event, "content_kind", None) == "a2ui":
            internal_type = "response.ui.component"
        else:
            internal_type = _AGUI_TO_INTERNAL.get(event.type)
        if internal_type is None:
            return None

        payload = self._remap_fields(event, internal_type)
        data = json.dumps(payload, ensure_ascii=False)
        return f"event: {internal_type}\ndata: {data}\n\n"

    def _remap_fields(self, event: AgentStreamEvent, internal_type: str) -> dict[str, Any]:
        """将 AG-UI 字段映射到旧版字段名。"""
        base: dict[str, Any] = {
            "type": internal_type,
            "seq": event.seq,
            "run_id": event.run_id,
            "session_id": event.session_id,
        }

        if internal_type == "response.created":
            base["content"] = event.run_content
        elif internal_type == "response.step":
            base["content"] = event.step_name
        elif internal_type == "response.step.done":
            base["content"] = event.step_name
        elif internal_type == "response.content.delta":
            base["delta"] = event.delta
            base["output_index"] = 0
        elif internal_type == "response.tool_call.start":
            base["tool_name"] = event.tool_name
            base["tool_args"] = event.tool_args
        elif internal_type == "response.tool_call.result":
            base["tool_name"] = event.tool_name
            base["tool_result"] = event.tool_result
        elif internal_type == "response.ui.component":
            base["ui_component"] = event.custom_data
        elif internal_type == "response.completed":
            base["message"] = event.message
            base["usage"] = event.usage
            base["turns"] = event.turns
            base["tool_calls"] = event.tool_calls
        elif internal_type == "response.failed":
            base["error_message"] = event.error_message

        return {k: v for k, v in base.items() if v is not None}


# ============ Enterprise AGUI Envelope ============


class EnterpriseAGUIFormatter:
    """将 AG-UI 事件包装为企业 AGUI 信封格式（AGUIEnvelope）。

    source_bu_type / app_type 在构造时注入。
    """

    def __init__(self, source_bu_type: str = "", app_type: str = "") -> None:
        self._source_bu_type = source_bu_type
        self._app_type = app_type

    def format(self, event: AgentStreamEvent) -> str:
        data_payload = self._build_data(event)
        envelope = AGUIEnvelope(
            id=event.seq,
            event=event.type,
            source_bu_type=self._source_bu_type,
            app_type=self._app_type,
            data=data_payload,
        )
        payload = envelope.model_dump_json(exclude_none=True)
        return f"event: {event.type}\ndata: {payload}\n\n"

    def _build_data(self, event: AgentStreamEvent) -> AGUIDataPayload:
        """根据事件类型填充 ui_protocol 和 ui_data。

        message_id: 文本消息事件用 event.message_id（跨事件关联键），其余留 None。
        conversation_id: 映射到 session_id。
        """
        dp = AGUIDataPayload(
            message_id=event.message_id,  # only non-None for text_message_* events
            conversation_id=event.session_id,
        )

        if event.type == "run_started":
            dp.ui_protocol = "text"
            dp.ui_data = event.run_content or ""
        elif event.type == "text_message_content":
            if getattr(event, "content_kind", None) == "a2ui":
                dp.ui_protocol = "A2UI"
                dp.ui_data = event.custom_data
            else:
                dp.ui_protocol = "text"
                dp.ui_data = event.delta or ""
        elif event.type in ("step_started", "step_finished"):
            dp.ui_protocol = "json"
            status = 1 if event.type == "step_started" else 0
            dp.ui_data = {"think": event.step_name, "think_status": status}
        elif event.type in ("tool_call_start", "tool_call_args", "tool_call_end"):
            dp.ui_protocol = "json"
            dp.ui_data = {"think": f"正在调用 {event.tool_name}", "think_status": 1}
        elif event.type == "tool_call_result":
            dp.ui_protocol = "json"
            dp.ui_data = {"think": f"{event.tool_name} 调用完成", "think_status": 0}
        elif event.type == "run_finished":
            dp.ui_protocol = "text"
            dp.ui_data = event.message or ""
        elif event.type == "run_error":
            dp.ui_protocol = "text"
            dp.ui_data = event.error_message or ""
        else:
            # text_message_start/end, state_snapshot, etc. — no ui_data needed
            dp.ui_protocol = "text"
            dp.ui_data = ""

        return dp


# ============ ALONE Protocol ============

_AGUI_TO_ALONE: dict[str, str] = {
    "run_started": "sa_ready",
    "text_message_content": "sa_stream_chunk",
    "step_started": "sa_stream_think",
    "run_finished": "sa_stream_complete",
    "run_error": "sa_error",
}

_SKIP_ALONE = {
    "text_message_start",
    "text_message_end",
    "step_finished",
    "tool_call_start",
    "tool_call_args",
    "tool_call_end",
    "tool_call_result",
    "custom",
    "state_snapshot",
    "state_delta",
    "messages_snapshot",
    "raw",
}


class AloneFormatter:
    """将 AG-UI 事件映射到旧版 ALONE 协议（sa_* 事件）。

    对齐 A2UI-design.md §3.2.1 前端对接协议。
    run_finished → sa_stream_complete + sa_done（规范要求 sa_done 作为连接终止信号）。
    """

    def format(self, event: AgentStreamEvent) -> str | None:
        if event.type in _SKIP_ALONE:
            return None
        if event.type == "text_message_content" and getattr(event, "content_kind", None) == "a2ui":
            return None

        alone_type = _AGUI_TO_ALONE.get(event.type)
        if alone_type is None:
            return None

        payload = self._build_payload(event, alone_type)
        data = json.dumps(payload, ensure_ascii=False)
        result = f"event: {alone_type}\ndata: {data}\n\n"

        # §3.2.1: sa_done 紧随 sa_stream_complete，通知客户端关闭连接
        if alone_type == "sa_stream_complete":
            import time
            done_data = json.dumps({"timestamp": str(int(time.time() * 1000))}, ensure_ascii=False)
            result += f"event: sa_done\ndata: {done_data}\n\n"

        return result

    def _build_payload(self, event: AgentStreamEvent, alone_type: str) -> dict[str, Any]:
        if alone_type == "sa_ready":
            return {"status": "ready", "message": "Agent initialized"}
        elif alone_type == "sa_stream_chunk":
            return {"content": event.delta or "", "index": event.seq}
        elif alone_type == "sa_stream_think":
            return {"thought": event.step_name or ""}
        elif alone_type == "sa_stream_complete":
            return {
                "content": event.message or "",
                "usage": event.usage or {},
            }
        elif alone_type == "sa_error":
            return {"code": 500, "message": event.error_message or "Unknown error"}
        return {}


# ============ Factory ============

_FORMATTERS: dict[str, type] = {
    "agui": BareAGUIFormatter,
    "internal": LegacyInternalFormatter,
    "enterprise": EnterpriseAGUIFormatter,
    "alone": AloneFormatter,
}


def create_formatter(
    protocol: str = "internal",
    *,
    source_bu_type: str = "",
    app_type: str = "",
) -> OutputFormatter:
    """创建 OutputFormatter 实例。

    Args:
        protocol: 协议标识 (agui / internal / enterprise / alone)
        source_bu_type: 企业 BU 类型（仅 enterprise 模式使用）
        app_type: App 类型（仅 enterprise 模式使用）
    """
    if protocol == "enterprise":
        return EnterpriseAGUIFormatter(source_bu_type=source_bu_type, app_type=app_type)
    cls = _FORMATTERS.get(protocol, LegacyInternalFormatter)
    return cls()
