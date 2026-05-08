"""create_cite_annotation_hook — factory for the BeforeLoopEnd citation hook.

Wiring:
    hook = create_cite_annotation_hook(tool_registry=self.tool_registry)
    return RunnerCallbacks(before_loop_end=[hook])

Contract:
  - Fires only when response.tool_calls is empty (final answer).
  - Returns CallbackResult(event=CallbackEvent(type="citation_batch", ...));
    run_hooks dispatches via dispatch_event → handler.on_citation × N +
    handler.on_citation_list × 1. The hook itself never touches handler.
  - Calls build_tool_sources_from_session(session, tool_registry=registry)
    which filters to tool_call results from tools with data_source=True.
  - Passes tool_sources to CiteAnnotator.annotate(answer, tool_sources).
  - Returns None (PASS) when there are no spans; never modifies the answer text.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..runtime.callbacks import BeforeLoopEndCallback, CallbackContext, CallbackResult
    from ..tools.registry import ToolRegistry
    from ..utils.entities import EntityTrie
    from .protocol import CiteAnnotator

logger = logging.getLogger(__name__)


def create_cite_annotation_hook(
    tool_registry: "ToolRegistry",
    annotator: "CiteAnnotator | None" = None,
    entity_trie: "EntityTrie | None" = None,
) -> "BeforeLoopEndCallback":
    """Return a BeforeLoopEndCallback that annotates the final answer with citations.

    Args:
        tool_registry:  Agent tool registry; used to filter to data_source=True tools.
        annotator:      Custom CiteAnnotator; defaults to DefaultCiteAnnotator.
        entity_trie:    Optional EntityTrie passed to DefaultCiteAnnotator when
                        annotator is None.
    """
    from .annotator import DefaultCiteAnnotator

    _annotator: "CiteAnnotator" = annotator or DefaultCiteAnnotator(entity_trie=entity_trie)

    async def _hook(
        ctx: "CallbackContext",
        *,
        response: Any,
        **kwargs: Any,
    ) -> "CallbackResult | None":
        if response.tool_calls:
            return None

        content = response.content or ""
        if not content.strip():
            return None

        from ..runtime.validation import build_tool_sources_from_session

        tool_sources = build_tool_sources_from_session(
            ctx.session,
            tool_registry=tool_registry,
        )
        if not tool_sources:
            return None

        spans, entries = _annotator.annotate(content, tool_sources)
        logger.debug(
            "[CITE_HOOK] session=%s tool_keys=%d spans=%d entries=%d",
            ctx.session.session_id,
            len(tool_sources),
            len(spans),
            len(entries),
        )

        if not spans:
            return None

        from ..runtime.callbacks import CallbackEvent, CallbackResult

        return CallbackResult(
            event=CallbackEvent(
                type="citation_batch",
                data={
                    "spans": spans,
                    "entries": entries,
                },
            )
        )

    return _hook  # type: ignore[return-value]
