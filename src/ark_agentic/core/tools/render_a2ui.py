"""
Unified A2UI rendering tool with three mutually-exclusive paths:

  blocks      → dynamic block/component composition  → full A2UI event
  card_type   → template.json + extractor            → full A2UI event
  preset_type → extractor → frontend-ready payload   → lean preset

Parameters exposed to the LLM are generated dynamically based on which
modes are configured via BlocksConfig / TemplateConfig / PresetRegistry.
"""

from __future__ import annotations

import itertools
import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol

from .base import AgentTool, ToolParameter
from ..types import AgentToolResult, ToolCall
from ..a2ui import render_from_template
from ..a2ui.blocks import _comp, A2UIOutput, IdGen
from ..a2ui.theme import A2UITheme
from ..a2ui.composer import BlockComposer, resolve_block_data
from ..a2ui.guard import validate_full_payload
from ..a2ui.preset_registry import PresetRegistry

logger = logging.getLogger(__name__)

_composer = BlockComposer()


class CardExtractor(Protocol):
    """卡片数据提取器契约。

    入参: (context, card_args)。返回 A2UIOutput，其中 template_data 供模板渲染，
    llm_digest / state_delta 由 render_a2ui 统一路由。
    """

    def __call__(self, context: dict[str, Any], card_args: dict[str, Any] | None) -> A2UIOutput: ...


# ---------------------------------------------------------------------------
# Config objects — group mode-specific parameters
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BlocksConfig:
    """Configuration for the *blocks* rendering mode (dynamic composition)."""

    agent_blocks: dict[str, Callable] = field(default_factory=dict)
    agent_components: dict[str, Callable] = field(default_factory=dict)
    theme: A2UITheme | None = None
    component_schemas: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class TemplateConfig:
    """Configuration for the *card_type* rendering mode (template.json)."""

    template_root: Path
    extractors: dict[str, CardExtractor]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _attach_enrichment(result: AgentToolResult, output: A2UIOutput) -> None:
    """Route llm_digest and state_delta from A2UIOutput into AgentToolResult."""
    if output.llm_digest:
        result.llm_digest = output.llm_digest
    if output.state_delta:
        existing = result.metadata.get("state_delta") or {}
        existing.update(output.state_delta)
        result.metadata["state_delta"] = existing


class _CardArgsError(Exception):
    pass


def _parse_card_args(args: dict[str, Any]) -> dict[str, Any] | None:
    """Parse the optional card_args JSON string from tool arguments.

    Raises ``_CardArgsError`` when the raw value is present but not valid JSON.
    """
    card_args_raw = args.get("card_args")
    if card_args_raw is None or not str(card_args_raw).strip():
        return None
    try:
        parsed = json.loads(str(card_args_raw))
    except json.JSONDecodeError as e:
        raise _CardArgsError(f"card_args 不是合法 JSON: {e}") from e
    return parsed if isinstance(parsed, dict) else None


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------

class RenderA2UITool(AgentTool):
    """Unified A2UI rendering tool.

    Supports up to three rendering modes, each enabled by its config object:

    - **blocks** (``BlocksConfig``): LLM provides block descriptors →
      BlockComposer expands into a full A2UI event payload.
    - **card_type** (``TemplateConfig``): loads template.json + extractor →
      full A2UI event payload.
    - **preset_type** (``PresetRegistry``): extractor produces a
      frontend-ready payload returned as-is (lean preset).

    Modes are mutually exclusive *per call*; a single tool instance may
    support multiple modes simultaneously.  LLM-visible ``parameters`` are
    generated dynamically based on which configs are provided.
    """

    name = "render_a2ui"
    description = "生成A2UI卡片内容,供UI渲染。"
    thinking_hint = "正在生成内容卡片..."

    group: str | None = None

    _MAX_CARD_DEPTH = 3

    @property
    def _theme(self) -> A2UITheme:
        if self._blocks and self._blocks.theme:
            return self._blocks.theme
        return A2UITheme()

    def __init__(
        self,
        blocks: BlocksConfig | None = None,
        template: TemplateConfig | None = None,
        preset: PresetRegistry | None = None,
        group: str | None = None,
        state_keys: tuple[str, ...] = (),
    ):
        self._blocks = blocks
        self._template = template
        self._preset = preset
        self._state_keys = state_keys

        if group is not None:
            self.group = group

        self.description = self._build_description()
        self.parameters = self._build_parameters()

    # ---- dynamic parameter generation ----

    def _build_description(self) -> str:
        modes: list[str] = []
        if self._blocks:
            modes.append("blocks 模式（动态组合）")
        if self._template:
            modes.append("card_type 模式（模板渲染）")
        if self._preset:
            modes.append("preset_type 模式（预设卡片）")
        if not modes:
            return "[UI渲染] 渲染 A2UI 卡片。"
        suffix = "；".join(modes)
        exclusive = "互斥，每次只传其一。" if len(modes) > 1 else ""
        return f"{self.description}。{suffix}。{exclusive}"

    def _build_parameters(self) -> list[ToolParameter]:
        params: list[ToolParameter] = []

        if self._blocks:
            available_types = (
                sorted(self._blocks.agent_blocks.keys())
                + ["Card"]
                + sorted(self._blocks.agent_components.keys())
            )
            blocks_desc = ", ".join(available_types)
            exclusive = self._exclusive_hint("blocks")
            desc = (
                f"块描述 JSON 数组字符串。每个元素为 {{\"type\": \"BlockType\", \"data\": {{...}}}}。"
                f"可用类型：{blocks_desc}。{exclusive}"
            )
            if self._blocks.component_schemas:
                schema_lines = "\n".join(
                    f"- {name}: {schema}"
                    for name, schema in self._blocks.component_schemas.items()
                )
                desc += f"\n组件说明：\n{schema_lines}"
            params.append(ToolParameter(
                name="blocks",
                type="string",
                description=desc,
                required=False,
            ))

        if self._template:
            card_types = list(self._template.extractors.keys())
            exclusive = self._exclusive_hint("card_type")
            params.append(ToolParameter(
                name="card_type",
                type="string",
                description=f"预定义卡片类型，加载对应模板渲染。{exclusive}",
                required=False,
                enum=card_types if card_types else None,
            ))

        if self._preset:
            preset_types = self._preset.types
            exclusive = self._exclusive_hint("preset_type")
            params.append(ToolParameter(
                name="preset_type",
                type="string",
                description=f"预设卡片类型，直接渲染数据卡片。{exclusive}",
                required=False,
                enum=preset_types if preset_types else None,
            ))

        if self._template or self._preset:
            params.append(ToolParameter(
                name="card_args",
                type="string",
                description="可选 JSON 参数（文案等），供 card_type / preset_type 使用。",
                required=False,
            ))

        if self._blocks or self._template:
            params.append(ToolParameter(
                name="surface_id",
                type="string",
                description="已有画布 ID。有则更新已有画布（surfaceUpdate），无则创建新画布。",
                required=False,
            ))

        return params

    def _exclusive_hint(self, current: str) -> str:
        others: list[str] = []
        if self._blocks and current != "blocks":
            others.append("blocks")
        if self._template and current != "card_type":
            others.append("card_type")
        if self._preset and current != "preset_type":
            others.append("preset_type")
        if not others:
            return ""
        return f"与 {', '.join(others)} 互斥。"

    # ---- execute dispatch ----

    async def execute(
        self, tool_call: ToolCall, context: dict[str, Any] | None = None
    ) -> AgentToolResult:
        ctx = context or {}
        args = tool_call.arguments

        blocks_raw = args.get("blocks")
        card_type = (args.get("card_type") or "").strip()
        preset_type = (args.get("preset_type") or "").strip()

        has_blocks = bool(blocks_raw is not None and str(blocks_raw).strip())
        has_card_type = bool(card_type)
        has_preset_type = bool(preset_type)

        chosen = has_blocks + has_card_type + has_preset_type
        if chosen > 1:
            return AgentToolResult.error_result(
                tool_call.id, "blocks / card_type / preset_type 互斥，只能传其一。"
            )
        if chosen == 0:
            return AgentToolResult.error_result(
                tool_call.id, "必须传入 blocks、card_type 或 preset_type 之一。"
            )

        if has_blocks:
            return await self._execute_blocks(tool_call, ctx, args)
        if has_card_type:
            return await self._execute_template(tool_call, ctx, card_type, args)
        return await self._execute_preset(tool_call, ctx, preset_type, args)

    # ---- blocks path ----

    async def _execute_blocks(
        self, tool_call: ToolCall, ctx: dict[str, Any], args: dict[str, Any]
    ) -> AgentToolResult:
        if not self._blocks:
            return AgentToolResult.error_result(
                tool_call.id, "blocks 模式不可用：未配置 BlocksConfig。"
            )

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

        raw_data = _collect_raw_data(ctx, self._state_keys)

        if not self._blocks.agent_blocks and not self._blocks.agent_components:
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

        counter = itertools.count(1)
        id_gen: IdGen = lambda prefix: f"{prefix.lower()}-{next(counter):03d}"

        root_children: list[str] = []
        all_components: list[dict[str, Any]] = []
        digest_parts: list[str] = []
        component_state: dict[str, Any] = {}

        for desc in block_descriptors:
            try:
                output = self._expand_one(desc, id_gen, raw_data)
            except Exception as e:
                return AgentToolResult.error_result(
                    tool_call.id, f"渲染失败: {e}"
                )
            if output.components:
                root_children.append(output.components[0]["id"])
                all_components.extend(output.components)
            if output.llm_digest:
                digest_parts.append(output.llm_digest)
            if output.state_delta:
                for key, value in output.state_delta.items():
                    if key in component_state and isinstance(component_state[key], list) and isinstance(value, list):
                        component_state[key].extend(value)
                    else:
                        component_state[key] = value

        root_id = id_gen("root")
        root = _comp(root_id, "Column", {
            "width": 100,
            "backgroundColor": self._theme.page_bg,
            "padding": self._theme.root_padding,
            "gap": self._theme.root_gap,
            "children": {"explicitList": root_children},
        })

        session_id = str(ctx.get("session_id", ""))
        prefix = session_id.strip()[:8] if session_id.strip() else "default"
        sid = surface_id or f"dyn-{prefix}-{uuid.uuid4().hex[:8]}"

        payload: dict[str, Any] = {
            "event": event,
            "version": "1.0.0",
            "surfaceId": sid,
            "rootComponentId": root_id,
            "style": "default",
            "data": {},
            "components": [root] + all_components,
        }
        result = self._validate_and_return(tool_call, payload)
        merged = A2UIOutput(
            llm_digest="\n".join(digest_parts),
            state_delta=component_state or None,
        )
        _attach_enrichment(result, merged)
        return result

    def _expand_one(
        self,
        desc: dict[str, Any],
        id_gen: IdGen,
        raw_data: dict[str, Any],
        _depth: int = 0,
    ) -> A2UIOutput:
        if not self._blocks:
            raise ValueError("blocks 模式不可用")

        block_type = desc.get("type", "")

        if block_type == "Card":
            card_data = desc.get("data", {})
            non_children = {k: v for k, v in card_data.items() if k != "children"}
            resolved = resolve_block_data(non_children, raw_data) if raw_data else non_children
            resolved["children"] = card_data.get("children", [])
            return self._expand_card(resolved, id_gen, raw_data, _depth)

        block_data = resolve_block_data(desc.get("data", {}), raw_data) if raw_data else desc.get("data", {})

        if block_type in self._blocks.agent_components:
            return self._blocks.agent_components[block_type](block_data, id_gen, raw_data)

        if block_type in self._blocks.agent_blocks:
            return A2UIOutput(
                components=self._blocks.agent_blocks[block_type](block_data, id_gen),
            )

        available = sorted(
            list(self._blocks.agent_blocks.keys())
            + ["Card"]
            + list(self._blocks.agent_components.keys())
        )
        raise ValueError(f"Unknown type '{block_type}'. Available: {available}")

    def _expand_card(
        self,
        data: dict[str, Any],
        id_gen: IdGen,
        raw_data: dict[str, Any],
        _depth: int = 0,
    ) -> A2UIOutput:
        if _depth >= self._MAX_CARD_DEPTH:
            raise ValueError(f"Card 嵌套超过 {self._MAX_CARD_DEPTH} 层")

        card_id, col_id = id_gen("card"), id_gen("column")
        child_ids: list[str] = []
        all_comps: list[dict[str, Any]] = []
        all_digests: list[str] = []
        merged_state: dict[str, Any] = {}

        for child_desc in data.get("children", []):
            child = self._expand_one(child_desc, id_gen, raw_data, _depth=_depth + 1)
            if child.components:
                child_ids.append(child.components[0]["id"])
                all_comps.extend(child.components)
            if child.llm_digest:
                all_digests.append(child.llm_digest)
            if child.state_delta:
                for k, v in child.state_delta.items():
                    if k in merged_state and isinstance(merged_state[k], list) and isinstance(v, list):
                        merged_state[k].extend(v)
                    else:
                        merged_state[k] = v

        col = _comp(col_id, "Column", {
            "gap": data.get("gap", self._theme.header_gap),
            "children": {"explicitList": child_ids},
        })
        card = _comp(card_id, "Card", {
            "width": 100,
            "backgroundColor": self._theme.card_bg,
            "borderRadius": self._theme.card_radius,
            "padding": data.get("padding", self._theme.card_padding),
            "children": {"explicitList": [col_id]},
        })
        return A2UIOutput(
            components=[card, col] + all_comps,
            llm_digest="\n".join(all_digests),
            state_delta=merged_state or None,
        )

    # ---- template path ----

    async def _execute_template(
        self, tool_call: ToolCall, ctx: dict[str, Any], card_type: str, args: dict[str, Any]
    ) -> AgentToolResult:
        if self._template is None:
            return AgentToolResult.error_result(
                tool_call.id, "card_type 模式不可用：未配置 TemplateConfig。"
            )
        if card_type not in self._template.extractors:
            return AgentToolResult.error_result(
                tool_call.id,
                f"不支持的卡片类型: {card_type}。可选: {', '.join(self._template.extractors.keys())}",
            )

        try:
            card_args = _parse_card_args(args)
        except _CardArgsError as e:
            return AgentToolResult.error_result(tool_call.id, str(e))

        extractor = self._template.extractors[card_type]
        try:
            output = extractor(ctx, card_args)
        except Exception as e:
            logger.exception("提取器执行失败: card_type=%s", card_type)
            return AgentToolResult.error_result(
                tool_call.id, f"数据提取失败: {e}"
            )

        flat_data = output.template_data
        session_id = str(ctx.get("session_id", ""))
        try:
            payload = render_from_template(
                self._template.template_root,
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

        result = self._validate_and_return(tool_call, payload)
        _attach_enrichment(result, output)
        return result

    # ---- preset path ----

    async def _execute_preset(
        self, tool_call: ToolCall, ctx: dict[str, Any], preset_type: str, args: dict[str, Any]
    ) -> AgentToolResult:
        if not self._preset:
            return AgentToolResult.error_result(
                tool_call.id, "preset_type 模式不可用：未配置 PresetRegistry。"
            )

        extractor = self._preset.get(preset_type)
        if extractor is None:
            return AgentToolResult.error_result(
                tool_call.id,
                f"不支持的预设类型: {preset_type}。可选: {', '.join(self._preset.types)}",
            )

        try:
            card_args = _parse_card_args(args)
        except _CardArgsError as e:
            return AgentToolResult.error_result(tool_call.id, str(e))

        try:
            output = extractor(ctx, card_args)
        except Exception as e:
            logger.exception("预设提取器执行失败: preset_type=%s", preset_type)
            return AgentToolResult.error_result(
                tool_call.id, f"数据提取失败: {e}"
            )

        result = AgentToolResult.a2ui_result(tool_call.id, output.template_data)
        _attach_enrichment(result, output)
        return result

    # ---- shared validation (blocks + template paths) ----

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


def _collect_raw_data(
    ctx: dict[str, Any],
    state_keys: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Collect raw business data from context via state_keys."""
    raw: dict[str, Any] = {}

    for key in state_keys:
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

    return raw
