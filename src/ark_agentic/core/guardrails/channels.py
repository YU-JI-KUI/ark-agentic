"""Shared helpers for guardrails-visible payload channels."""

from __future__ import annotations

from typing import Any


GUARDRAILS_METADATA_KEY = "guardrails"


def get_guardrails_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    if not metadata:
        return {}
    raw = metadata.get(GUARDRAILS_METADATA_KEY)
    return raw if isinstance(raw, dict) else {}


def ensure_guardrails_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    if metadata is None:
        metadata = {}
    payload = metadata.get(GUARDRAILS_METADATA_KEY)
    if not isinstance(payload, dict):
        payload = {}
        metadata[GUARDRAILS_METADATA_KEY] = payload
    return payload


def set_visible_channels(
    metadata: dict[str, Any],
    *,
    llm_visible_content: Any | None = None,
    ui_visible_content: Any | None = None,
    contains_sensitive: bool | None = None,
) -> dict[str, Any]:
    # 同一份工具结果可以给不同消费方看到不同内容：
    # LLM 侧用于后续推理上下文，UI 侧用于前端展示。
    payload = ensure_guardrails_metadata(metadata)
    if llm_visible_content is not None:
        payload["llm_visible_content"] = llm_visible_content
    if ui_visible_content is not None:
        payload["ui_visible_content"] = ui_visible_content
    if contains_sensitive is not None:
        payload["contains_sensitive"] = contains_sensitive
    return payload


def resolve_llm_visible_content(raw_content: Any, metadata: dict[str, Any] | None) -> Any:
    payload = get_guardrails_metadata(metadata)
    return payload.get("llm_visible_content", raw_content)


def resolve_ui_visible_content(raw_content: Any, metadata: dict[str, Any] | None) -> Any:
    payload = get_guardrails_metadata(metadata)
    return payload.get("ui_visible_content", raw_content)
