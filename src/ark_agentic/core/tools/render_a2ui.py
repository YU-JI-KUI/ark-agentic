"""
Unified A2UI rendering tool: blocks path + optional card_type template path.

Two paths via mutual-exclusion:
  blocks   → BlockComposer pipeline (dynamic block composition)
  card_type → render_from_template pipeline (deterministic JSON template)

surface_id presence implies surfaceUpdate; absence implies beginRendering.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Protocol

from .base import AgentTool, ToolParameter
from ..types import AgentToolResult, ToolCall
from ..a2ui import render_from_template
from ..a2ui.composer import BlockComposer
from ..a2ui.guard import validate_full_payload

logger = logging.getLogger(__name__)

_composer = BlockComposer()


class CardExtractor(Protocol):
    """卡片数据提取器契约。

    入参: (context, card_args)。返回扁平 dict 供 render_from_template 合并到模板 data。
    """

    def __call__(self, context: dict[str, Any], card_args: dict[str, Any] | None) -> dict[str, Any]: ...


class RenderA2UITool(AgentTool):
    """Unified A2UI rendering tool.

    blocks path: LLM provides block descriptors (+optional transforms) →
        BlockComposer expands into full A2UI payload.
    card_type path: loads template.json + extractor → full A2UI payload.

    Both paths share the same validation pipeline.
    """

    name = "render_a2ui"
    description = (
        "渲染 A2UI 卡片。"
        "blocks 模式：传入块描述数组动态组合；"
        "card_type 模式：加载预定义模板。二者互斥。"
    )

    group: str | None = None

    def __init__(
        self,
        template_root: str | Path | None = None,
        extractors: dict[str, CardExtractor] | None = None,
        group: str | None = None,
    ):
        self._template_root = Path(template_root) if template_root else None
        self._extractors: dict[str, CardExtractor] = dict(extractors or {})

        card_types = list(self._extractors.keys())
        self.parameters = [
            ToolParameter(
                name="blocks",
                type="string",
                description=(
                    "块描述 JSON 数组字符串。每个元素为 {\"type\": \"BlockType\", \"data\": {...}}。"
                    "可用块类型：SummaryHeader, SectionCard, InfoCard, AdviceCard, "
                    "KeyValueList, ItemList, ActionButton, ButtonGroup, "
                    "Divider, TagRow, ImageBanner, StatusRow, FundsSummary。"
                    "与 card_type 互斥。"
                ),
                required=False,
            ),
            ToolParameter(
                name="card_type",
                type="string",
                description="预定义卡片类型，加载对应模板渲染。与 blocks 互斥。",
                required=False,
                enum=card_types if card_types else None,
            ),
            ToolParameter(
                name="card_args",
                type="string",
                description="card_type 模式下的可选 JSON 参数（文案等）。",
                required=False,
            ),
            ToolParameter(
                name="surface_id",
                type="string",
                description="已有画布 ID。有则更新已有画布（surfaceUpdate），无则创建新画布。",
                required=False,
            ),
        ]
        if group is not None:
            self.group = group

    async def execute(
        self, tool_call: ToolCall, context: dict[str, Any] | None = None
    ) -> AgentToolResult:
        ctx = context or {}
        args = tool_call.arguments

        blocks_raw = args.get("blocks")
        card_type = (args.get("card_type") or "").strip()
        has_blocks = blocks_raw is not None and str(blocks_raw).strip()
        has_card_type = bool(card_type)

        if has_blocks and has_card_type:
            return AgentToolResult.error_result(
                tool_call.id, "blocks 和 card_type 互斥，只能传其一。"
            )
        if not has_blocks and not has_card_type:
            return AgentToolResult.error_result(
                tool_call.id, "必须传入 blocks 或 card_type 之一。"
            )

        if has_blocks:
            return await self._execute_blocks(tool_call, ctx, args)
        return await self._execute_template(tool_call, ctx, card_type, args)

    # ---- blocks path ----

    async def _execute_blocks(
        self, tool_call: ToolCall, ctx: dict[str, Any], args: dict[str, Any]
    ) -> AgentToolResult:
        blocks_raw = args.get("blocks", "")
        surface_id = (args.get("surface_id") or "").strip()
        event = "surfaceUpdate" if surface_id else "beginRendering"

        try:
            block_descriptors = json.loads(str(blocks_raw))
        except json.JSONDecodeError as e:
            return AgentToolResult.error_result(
                tool_call.id, f"blocks 不是合法 JSON: {e}"
            )
        if not isinstance(block_descriptors, list):
            return AgentToolResult.error_result(
                tool_call.id, "blocks 必须是 JSON 数组"
            )

        raw_data = _collect_raw_data(ctx)

        session_id = str(ctx.get("session_id", ""))
        try:
            payload = _composer.compose(
                block_descriptors,
                data={},
                event=event,
                surface_id=surface_id,
                session_id=session_id,
                raw_data=raw_data,
            )
        except (ValueError, KeyError) as e:
            return AgentToolResult.error_result(
                tool_call.id, f"块组合失败: {e}"
            )
        except Exception as e:
            logger.exception("Unexpected composer error")
            return AgentToolResult.error_result(
                tool_call.id, f"组合失败: {e}"
            )

        return self._validate_and_return(tool_call, payload)

    # ---- template path ----

    async def _execute_template(
        self, tool_call: ToolCall, ctx: dict[str, Any], card_type: str, args: dict[str, Any]
    ) -> AgentToolResult:
        if self._template_root is None or not self._extractors:
            return AgentToolResult.error_result(
                tool_call.id, "card_type 模式不可用：未配置模板或提取器。"
            )
        if card_type not in self._extractors:
            return AgentToolResult.error_result(
                tool_call.id,
                f"不支持的卡片类型: {card_type}。可选: {', '.join(self._extractors.keys())}",
            )

        card_args_raw = args.get("card_args")
        card_args: dict[str, Any] | None = None
        if card_args_raw is not None and str(card_args_raw).strip():
            try:
                card_args = json.loads(str(card_args_raw))
            except json.JSONDecodeError as e:
                return AgentToolResult.error_result(
                    tool_call.id, f"card_args 不是合法 JSON: {e}"
                )
            if not isinstance(card_args, dict):
                card_args = None

        extractor = self._extractors[card_type]
        try:
            flat_data = extractor(ctx, card_args)
        except Exception as e:
            logger.exception("提取器执行失败: card_type=%s", card_type)
            return AgentToolResult.error_result(
                tool_call.id, f"数据提取失败: {e}"
            )

        session_id = str(ctx.get("session_id", ""))
        try:
            payload = render_from_template(
                self._template_root,
                card_type,
                flat_data,
                session_id=session_id,
            )
        except FileNotFoundError as e:
            return AgentToolResult.error_result(
                tool_call.id, f"模板不存在或渲染失败: {e}"
            )
        except json.JSONDecodeError as e:
            return AgentToolResult.error_result(
                tool_call.id, f"模板 JSON 解析失败: {e}"
            )
        except Exception as e:
            logger.exception("渲染失败: card_type=%s", card_type)
            return AgentToolResult.error_result(
                tool_call.id, f"模板不存在或渲染失败: {e}"
            )

        return self._validate_and_return(tool_call, payload)

    # ---- shared validation ----

    def _validate_and_return(
        self,
        tool_call: ToolCall,
        payload: dict[str, Any],
    ) -> AgentToolResult:
        strict_mode = os.getenv("A2UI_STRICT_VALIDATION", "enforce")
        guard = validate_full_payload(payload, strict=(strict_mode == "enforce"))

        if guard.errors and strict_mode == "enforce":
            return AgentToolResult.error_result(
                tool_call.id,
                f"A2UI contract invalid: {guard.errors[0]}",
            )

        all_warnings = guard.errors + guard.warnings
        if all_warnings:
            for w in all_warnings:
                logger.warning(w)

        meta: dict[str, Any] = {}
        if all_warnings:
            meta["warnings"] = all_warnings
        meta["a2ui_validation"] = {
            "ok": guard.ok,
            "errors": guard.errors,
            "mode": strict_mode,
        }
        return AgentToolResult.a2ui_result(tool_call.id, payload, metadata=meta)


def _collect_raw_data(ctx: dict[str, Any]) -> dict[str, Any]:
    """Collect raw business data from context.

    Merges all tool results at top level so transforms can use clean paths
    like ``identity.name`` or ``options[0].product_name``.
    """
    raw: dict[str, Any] = {}

    _STATE_KEYS = (
        "_rule_engine_result",
        "_policy_query_result",
        "_customer_info_result",
    )
    for key in _STATE_KEYS:
        data = ctx.get(key)
        if data is None:
            continue
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError:
                continue
        if isinstance(data, dict):
            raw.update(data)

    by_name = ctx.get("_tool_results_by_name")
    if isinstance(by_name, dict):
        for _name, result in by_name.items():
            if isinstance(result, str):
                try:
                    result = json.loads(result)
                except json.JSONDecodeError:
                    continue
            if isinstance(result, dict):
                raw.update(result)

    return raw
