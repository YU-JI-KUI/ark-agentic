"""
Unified A2UI rendering tool: blocks path + optional card_type template path.

Two paths via mutual-exclusion:
  blocks   → agent pipeline (dynamic block/component composition)
  card_type → render_from_template pipeline (deterministic JSON template)

surface_id presence implies surfaceUpdate; absence implies beginRendering.
"""

from __future__ import annotations

import itertools
import json
import logging
import os
import uuid
from pathlib import Path
from typing import Any, Callable, Protocol

from .base import AgentTool, ToolParameter
from ..types import AgentToolResult, ToolCall
from ..a2ui import render_from_template
from ..a2ui.blocks import _comp, A2UIOutput, IdGen, PAGE_BG, CARD_BG, CARD_RADIUS
from ..a2ui.composer import BlockComposer, resolve_block_data
from ..a2ui.guard import validate_full_payload

logger = logging.getLogger(__name__)

_composer = BlockComposer()


class CardExtractor(Protocol):
    """卡片数据提取器契约。

    入参: (context, card_args)。返回 A2UIOutput，其中 template_data 供模板渲染，
    llm_digest / state_delta 由 render_a2ui 统一路由。
    """

    def __call__(self, context: dict[str, Any], card_args: dict[str, Any] | None) -> A2UIOutput: ...


def _attach_enrichment(result: AgentToolResult, output: A2UIOutput) -> None:
    """Route llm_digest and state_delta from A2UIOutput into AgentToolResult.metadata."""
    if output.llm_digest:
        result.metadata["llm_digest"] = output.llm_digest
    if output.state_delta:
        existing = result.metadata.get("state_delta") or {}
        existing.update(output.state_delta)
        result.metadata["state_delta"] = existing


class RenderA2UITool(AgentTool):
    """Unified A2UI rendering tool.

    blocks path: LLM provides block descriptors (+optional transforms) →
        BlockComposer expands into full A2UI payload.
    card_type path: loads template.json + extractor → full A2UI payload.

    Both paths share the same validation pipeline.
    """

    name = "render_a2ui"
    thinking_hint = "正在生成内容卡片..."
    description = (
        "渲染 A2UI 卡片。"
        "blocks 模式：传入块描述数组动态组合；"
        "card_type 模式：加载预定义模板。二者互斥。"
    )

    group: str | None = None

    _MAX_CARD_DEPTH = 3

    def __init__(
        self,
        template_root: str | Path | None = None,
        extractors: dict[str, CardExtractor] | None = None,
        group: str | None = None,
        agent_blocks: dict[str, Callable] | None = None,
        agent_components: dict[str, Callable] | None = None,
        root_gap: int = 0,
        root_padding: int | list[int] = 2,
        state_keys: tuple[str, ...] = (),
    ):
        self._template_root = Path(template_root) if template_root else None
        self._extractors: dict[str, CardExtractor] = dict(extractors or {})
        self._agent_blocks: dict[str, Callable] = dict(agent_blocks or {})
        self._agent_components: dict[str, Callable] = dict(agent_components or {})
        self._root_gap = root_gap
        self._root_padding = root_padding
        self._state_keys = state_keys

        card_types = list(self._extractors.keys())
        available_types = (
            sorted(self._agent_blocks.keys())
            + ["Card"]
            + sorted(self._agent_components.keys())
        )
        blocks_desc = ", ".join(available_types) if available_types != ["Card"] else "（未配置 agent blocks）"
        self.parameters = [
            ToolParameter(
                name="blocks",
                type="string",
                description=(
                    "块描述 JSON 数组字符串。每个元素为 {\"type\": \"BlockType\", \"data\": {...}}。"
                    f"可用类型：{blocks_desc}。"
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

        raw_data = _collect_raw_data(ctx, self._state_keys)

        if not self._agent_blocks and not self._agent_components:
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
            "backgroundColor": PAGE_BG,
            "padding": self._root_padding,
            "gap": self._root_gap,
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
        block_type = desc.get("type", "")

        if block_type == "Card":
            card_data = desc.get("data", {})
            non_children = {k: v for k, v in card_data.items() if k != "children"}
            resolved = resolve_block_data(non_children, raw_data) if raw_data else non_children
            resolved["children"] = card_data.get("children", [])
            return self._expand_card(resolved, id_gen, raw_data, _depth)

        block_data = resolve_block_data(desc.get("data", {}), raw_data) if raw_data else desc.get("data", {})

        if block_type in self._agent_components:
            return self._agent_components[block_type](block_data, id_gen, raw_data)

        if block_type in self._agent_blocks:
            return A2UIOutput(
                components=self._agent_blocks[block_type](block_data, id_gen),
            )

        available = sorted(
            list(self._agent_blocks.keys())
            + ["Card"]
            + list(self._agent_components.keys())
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
            "gap": data.get("gap", 8),
            "children": {"explicitList": child_ids},
        })
        card = _comp(card_id, "Card", {
            "width": 100,
            "backgroundColor": CARD_BG,
            "borderRadius": CARD_RADIUS,
            "padding": data.get("padding", 16),
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

        result = self._validate_and_return(tool_call, payload)
        _attach_enrichment(result, output)
        return result

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


def _collect_raw_data(
    ctx: dict[str, Any],
    state_keys: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Collect raw business data from context.

    Merges agent-specific state_delta keys (injected via ``state_keys``)
    and generic ``_tool_results_by_name`` so transforms can use clean paths
    like ``identity.name`` or ``options[0].product_name``.
    """
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
