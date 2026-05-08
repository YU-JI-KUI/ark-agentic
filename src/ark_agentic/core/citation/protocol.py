"""CiteAnnotator + SpanLocator — Protocols for citation annotation strategies."""

from __future__ import annotations

from typing import Protocol, TYPE_CHECKING

from .types import CiteEntry, CiteSpan

if TYPE_CHECKING:
    from ..runtime.validation import ExtractedClaim


class SpanLocator(Protocol):
    """Locate every occurrence of a single ``ExtractedClaim`` in the answer text.

    One implementation per claim type — keeps claim-specific text-matching
    rules (e.g. NUMBER's 千分位 alignment) out of the annotator. New claim
    types extend the system by registering a new ``SpanLocator``; the
    annotator stays closed for modification.
    """

    def find_spans(
        self, text: str, claim: "ExtractedClaim",
    ) -> list[tuple[int, int, str]]:
        """Return ``(start, end, raw_text)`` triples for every occurrence."""
        ...


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
        tool_sources: dict[str, str],
    ) -> tuple[list[CiteSpan], list[CiteEntry]]: ...
