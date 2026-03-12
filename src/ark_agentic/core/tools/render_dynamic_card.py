"""
Dynamic A2UI card rendering tool — Block Composer edition

LLM provides compact block descriptors + optional Transform DSL.
The tool expands blocks into a full A2UI payload via BlockComposer.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from .base import AgentTool, ToolParameter
from ..types import AgentToolResult, ToolCall
from ..a2ui.composer import BlockComposer
from ..a2ui.contract_models import validate_event_payload
from ..a2ui.transforms import execute_transforms
from ..a2ui.validator import validate_payload

logger = logging.getLogger(__name__)

_composer = BlockComposer()


class RenderDynamicCardTool(AgentTool):
    """Render an A2UI card from composable block descriptors.

    The LLM generates a compact list of block descriptors (SummaryHeader,
    SectionCard, AdviceCard, ActionButton, etc.) and an optional Transform
    DSL for data preparation.  All styling is hardcoded in Python builders.
    """

    name = "render_dynamic_card"
    description = (
        "根据可组合块描述动态生成 A2UI 卡片。"
        "blocks 是块描述数组（type + data），每个块自动展开为完整 A2UI 组件。"
        "通过 transforms 参数指定数据查询/格式化规则（get/sum/format/concat/select），"
        "数据从 context 中的工具结果自动获取，确保数字准确性。"
    )

    parameters = [
        ToolParameter(
            name="blocks",
            type="string",
            description=(
                "块描述 JSON 数组字符串。每个元素为 {\"type\": \"BlockType\", \"data\": {...}}。"
                "可用块类型：SummaryHeader, SectionCard, InfoCard, AdviceCard, "
                "KeyValueList, DataTable, ItemList, ActionButton, ButtonGroup, "
                "Divider, TagRow, ImageBanner, StatusRow。"
                "data 中使用 $field 引用数据。"
            ),
            required=True,
        ),
        ToolParameter(
            name="transforms",
            type="string",
            description=(
                "可选，Transform DSL JSON 字符串。"
                "指定如何从 context 原始数据派生 UI 所需的值。"
                "支持 get/sum/count/concat/select/literal 操作和 currency/percent 格式化。"
            ),
            required=False,
        ),
        ToolParameter(
            name="event",
            type="string",
            description=(
                "A2UI 事件类型，默认 beginRendering。"
                "可选: surfaceUpdate, dataModelUpdate, deleteSurface。"
            ),
            required=False,
        ),
        ToolParameter(
            name="surface_id",
            type="string",
            description="已有 surfaceId，用于 surfaceUpdate/dataModelUpdate 时指定目标画布。",
            required=False,
        ),
    ]

    group: str | None = None

    def __init__(self, group: str | None = None):
        if group is not None:
            self.group = group

    async def execute(
        self, tool_call: ToolCall, context: dict[str, Any] | None = None
    ) -> AgentToolResult:
        ctx = context or {}
        args = tool_call.arguments

        blocks_raw = args.get("blocks", "")
        transforms_raw = args.get("transforms")
        event = (args.get("event") or "beginRendering").strip()
        surface_id = (args.get("surface_id") or "").strip()

        # Parse blocks
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

        # Parse transforms
        transforms: dict[str, Any] = {}
        if transforms_raw and str(transforms_raw).strip():
            try:
                transforms = json.loads(str(transforms_raw))
            except json.JSONDecodeError as e:
                return AgentToolResult.error_result(
                    tool_call.id, f"transforms 不是合法 JSON: {e}"
                )
            if not isinstance(transforms, dict):
                transforms = {}

        # Build raw data from context
        raw_data = self._collect_raw_data(ctx)

        # Execute transforms
        computed_data: dict[str, Any] = {}
        transform_warnings: list[str] = []
        if transforms:
            computed_data, transform_warnings = execute_transforms(transforms, raw_data)

        # dataModelUpdate: only need surface_id + data
        if event == "dataModelUpdate":
            payload: dict[str, Any] = {
                "event": "dataModelUpdate",
                "version": "1.0.0",
                "surfaceId": surface_id or f"dyn-{ctx.get('session_id', '')[:8]}",
                "data": computed_data,
            }
            meta: dict[str, Any] = {}
            if transform_warnings:
                meta["warnings"] = transform_warnings
            return AgentToolResult.a2ui_result(tool_call.id, payload, metadata=meta)

        # deleteSurface: minimal payload
        if event == "deleteSurface":
            payload = {
                "event": "deleteSurface",
                "version": "1.0.0",
                "surfaceId": surface_id,
            }
            return AgentToolResult.a2ui_result(tool_call.id, payload)

        # Compose blocks into full A2UI payload
        session_id = str(ctx.get("session_id", ""))
        try:
            payload = _composer.compose(
                block_descriptors,
                computed_data,
                event=event,
                surface_id=surface_id,
                session_id=session_id,
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

        # Contract validation
        strict_mode = os.getenv("A2UI_STRICT_VALIDATION", "enforce")
        contract_errors: list[str] = []
        try:
            validate_event_payload(payload)
        except ValueError as e:
            contract_errors.append(f"[EVENT_CONTRACT] {e}")

        vr = validate_payload(payload)
        if not vr.ok:
            contract_errors.extend(
                f"[{code}] {err}"
                for code, err in zip(vr.error_codes, vr.errors)
            )

        if contract_errors and strict_mode == "enforce":
            return AgentToolResult.error_result(
                tool_call.id,
                f"A2UI contract invalid: {contract_errors[0]}",
            )

        all_warnings = transform_warnings + contract_errors
        if all_warnings:
            for w in all_warnings:
                logger.warning(w)

        meta = {}
        if all_warnings:
            meta["warnings"] = all_warnings
        meta["a2ui_validation"] = {
            "ok": vr.ok and not contract_errors,
            "errors": contract_errors,
            "mode": strict_mode,
        }

        return AgentToolResult.a2ui_result(tool_call.id, payload, metadata=meta)

    @staticmethod
    def _collect_raw_data(ctx: dict[str, Any]) -> dict[str, Any]:
        """Collect raw business data from context.

        Merges all tool results at top level so transforms can use clean paths
        like ``identity.name`` or ``options[0].product_name``.

        Data sources (later wins on key collision):
        1. Persisted state_delta keys from prior turns
        2. Same-turn tool results via ``_tool_results_by_name``
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
