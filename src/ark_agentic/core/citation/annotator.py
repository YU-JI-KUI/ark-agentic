"""DefaultCiteAnnotator + default SpanLocator implementations.

Strategy:
  1. extract_claims_from_answer(answer)  → list[ExtractedClaim]
  2. match_claim_sources(claim, tool_sources)  → list[matched tool keys]
  3. SpanLocator (per claim type) returns (start, end, raw_text) for each
     occurrence in the answer. ``NumberSpanLocator`` aligns 千分位 显示
     against grounding 面值; ``SubstringSpanLocator`` does verbatim ``find``.
  4. Assign deduplicated cite-N IDs by (tool_name, claim.value).
  5. Return (spans, entries).

tool_sources format: {"tool_<name>": normalized_text, ...}
(same dict produced by build_tool_sources_from_session)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .protocol import SpanLocator
from .types import CiteEntry, CiteSpan

if TYPE_CHECKING:
    from ..runtime.validation import ClaimExtractor, ExtractedClaim
    from ..utils.entities import EntityTrie

logger = logging.getLogger(__name__)


class SubstringSpanLocator:
    """Default locator: verbatim ``str.find`` over the claim value."""

    def find_spans(
        self, text: str, claim: "ExtractedClaim",
    ) -> list[tuple[int, int, str]]:
        value = claim.value
        if not value:
            return []
        out: list[tuple[int, int, str]] = []
        search_start = 0
        while True:
            idx = text.find(value, search_start)
            if idx == -1:
                break
            end = idx + len(value)
            out.append((idx, end, value))
            search_start = end
        return out


class NumberSpanLocator:
    """NUMBER locator: aligns claim.value (no 千分位) with text occurrences
    that may include 千分位（e.g. ``2,000.00`` vs claim ``2000``)."""

    def find_spans(
        self, text: str, claim: "ExtractedClaim",
    ) -> list[tuple[int, int, str]]:
        from ..utils.numbers import (
            canonical_number_claim_value,
            iter_number_spans_in_text,
        )

        out: list[tuple[int, int, str]] = []
        for start, end, raw_text, numeric, _ in iter_number_spans_in_text(text):
            if canonical_number_claim_value(numeric) != claim.value:
                continue
            out.append((start, end, raw_text))
        return out


def _default_locators() -> dict[str, SpanLocator]:
    substring = SubstringSpanLocator()
    return {
        "NUMBER": NumberSpanLocator(),
        "ENTITY": substring,
        "TIME": substring,
    }


class DefaultCiteAnnotator:
    """Cite annotator that piggybacks on the grounding infrastructure.

    Args:
        entity_trie: Optional EntityTrie for ENTITY claim extraction.
        extractors:  Override the default ClaimExtractor chain.
        locators:    Override the per-claim-type SpanLocator dispatch table.
                     Keys are claim types ("NUMBER" / "ENTITY" / "TIME" / …);
                     unknown types fall back to ``SubstringSpanLocator``.
    """

    def __init__(
        self,
        entity_trie: "EntityTrie | None" = None,
        extractors: "list[ClaimExtractor] | None" = None,
        locators: dict[str, SpanLocator] | None = None,
    ) -> None:
        self._entity_trie = entity_trie
        self._extractors = extractors
        self._locators: dict[str, SpanLocator] = locators or _default_locators()
        self._fallback_locator: SpanLocator = SubstringSpanLocator()

    def annotate(
        self,
        answer: str,
        tool_sources: dict[str, str],
    ) -> tuple[list[CiteSpan], list[CiteEntry]]:
        """Return (spans, entries) for the final answer.

        Spans are ordered by start offset; entries are deduplicated by
        (tool_name, matched_text) and ordered by cite-N assignment order.
        """
        from ..runtime.validation import (
            default_extractors,
            extract_claims_from_answer,
            match_claim_sources,
        )

        if not answer or not tool_sources:
            return [], []

        extractors = self._extractors or default_extractors(self._entity_trie)
        claims = extract_claims_from_answer(answer, extractors=extractors)

        cite_registry: dict[str, tuple[str, str, str]] = {}
        counter = 0
        spans: list[CiteSpan] = []

        for claim in claims:
            matched_keys = match_claim_sources(claim, tool_sources)
            if not matched_keys:
                continue

            locator = self._locators.get(claim.type, self._fallback_locator)
            span_locations = locator.find_spans(answer, claim)

            for idx, span_end, matched_text in span_locations:
                for key in matched_keys:
                    tool_name = key[len("tool_"):] if key.startswith("tool_") else key
                    cite_key = f"{tool_name}::{claim.value}"
                    if cite_key not in cite_registry:
                        counter += 1
                        cite_registry[cite_key] = (
                            f"cite-{counter}",
                            tool_name,
                            claim.value,
                        )
                    source_id, t_name, _ = cite_registry[cite_key]
                    spans.append(CiteSpan(
                        source_id=source_id,
                        tool_name=t_name,
                        start=idx,
                        end=span_end,
                        matched_text=matched_text,
                    ))

        spans.sort(key=lambda s: s.start)

        entries = [
            CiteEntry(source_id=sid, tool_name=t, matched_text=v)
            for _, (sid, t, v) in sorted(
                cite_registry.items(),
                key=lambda kv: int(kv[1][0].split("-")[1]),
            )
        ]

        logger.debug(
            "CiteAnnotator: %d spans, %d entries for answer len=%d",
            len(spans), len(entries), len(answer),
        )
        return spans, entries
