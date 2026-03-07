"""
通用 A2UI 渲染卡片工具

根据 card_type 调用对应提取器从 context + card_args 得到扁平 data，
再调用 core.a2ui.render_from_template 生成 A2UI 负载。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Protocol

from .base import AgentTool, ToolParameter
from ..types import AgentToolResult, ToolCall
from ..a2ui import render_from_template

logger = logging.getLogger(__name__)


class CardExtractor(Protocol):
    """
    卡片数据提取器契约。

    入参: (context, card_args)。context 含 session 状态（如 _rule_engine_result）、session_id 等；
    card_args 为工具解析后的 dict（可能为 None）。提取器仅从 card_args 读取约定文案字段（字符串），
    业务数据一律从 context 确定性计算。返回扁平 dict，供 render_from_template 合并到模板 data。
    异常可由 RenderCardTool 捕获并转为 error_result。
    """

    def __call__(self, context: dict[str, Any], card_args: dict[str, Any] | None) -> dict[str, Any]: ...


class RenderCardTool(AgentTool):
    """
    通用 A2UI 渲染卡片工具。

    构造时注入 template_root 与 extractors（card_type -> 提取器）。
    card_type 的 enum 由 extractors.keys() 生成；card_args 为可选 JSON 字符串。
    """

    name = "render_card"
    description = (
        "根据 card_type 渲染对应 A2UI 卡片，在前端展示。"
        "需先准备好数据源（如先调用 rule_engine 等），再传入 card_type 和可选的 card_args（文案等）。"
    )
    group: str | None = None

    def __init__(
        self,
        template_root: str | Path,
        extractors: dict[str, CardExtractor],
        group: str | None = None,
    ):
        self._template_root = Path(template_root)
        self._extractors = dict(extractors)
        card_types = list(self._extractors.keys())
        self.parameters = [
            ToolParameter(
                name="card_type",
                type="string",
                description="卡片类型，决定使用哪套模板与数据提取逻辑。",
                required=True,
                enum=card_types if card_types else None,
            ),
            ToolParameter(
                name="card_args",
                type="string",
                description="可选，JSON 对象字符串，如建议文案、按钮文案等，由具体卡片类型约定。",
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
        card_type = (args.get("card_type") or "").strip()
        card_args_raw = args.get("card_args")

        if card_type not in self._extractors:
            return AgentToolResult.error_result(
                tool_call.id,
                f"不支持的卡片类型: {card_type}。可选: {', '.join(self._extractors.keys())}",
            )

        card_args: dict[str, Any] | None = None
        if card_args_raw is not None and str(card_args_raw).strip():
            try:
                card_args = json.loads(str(card_args_raw))
            except json.JSONDecodeError as e:
                return AgentToolResult.error_result(
                    tool_call.id,
                    f"card_args 不是合法 JSON: {e}",
                )
            if not isinstance(card_args, dict):
                card_args = None

        extractor = self._extractors[card_type]
        try:
            flat_data = extractor(ctx, card_args)
        except Exception as e:
            logger.exception("提取器执行失败: card_type=%s", card_type)
            return AgentToolResult.error_result(
                tool_call.id,
                f"数据提取失败: {e}",
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
                tool_call.id,
                f"模板不存在或渲染失败: {e}",
            )
        except json.JSONDecodeError as e:
            return AgentToolResult.error_result(
                tool_call.id,
                f"模板 JSON 解析失败: {e}",
            )
        except Exception as e:
            logger.exception("渲染失败: card_type=%s", card_type)
            return AgentToolResult.error_result(
                tool_call.id,
                f"模板不存在或渲染失败: {e}",
            )

        return AgentToolResult.a2ui_result(tool_call.id, payload)
