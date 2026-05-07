"""CiteAnnotator — Protocol for citation annotation strategies."""

from __future__ import annotations

from typing import Any, Protocol

from .types import CiteEntry, CiteSpan


class CiteAnnotator(Protocol):
    """Annotate a final answer with citation spans and entries.

    Implementations receive the complete answer text and a dict of
    tool_name → normalized_source_text, and return:
      - spans: per-claim inline markers (start/end offsets into answer)
      - entries: deduplicated summary list for the citation_list event
    """

    def annotate(
        self,
        answer: str,
        tool_sources: dict[str, Any],
    ) -> tuple[list[CiteSpan], list[CiteEntry]]: ...
