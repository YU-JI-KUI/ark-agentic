"""DefaultCiteAnnotator — grounding ClaimExtractor + match_claim_sources.

Strategy:
  1. extract_claims_from_answer(answer)  → list[ExtractedClaim]
  2. match_claim_sources(claim, tool_sources)  → list[matched tool keys]
  3. For each matched claim, locate spans (NUMBER: 千分位等与 grounding 面值对齐；
     其它类型：子串 ``find``）。
  4. Assign deduplicated cite-N IDs by (tool_name, claim.value).
  5. Return (spans, entries).

tool_sources format: {"tool_<name>": normalized_text, ...}
(same dict produced by build_tool_sources_from_session)
"""

from __future__ import annotations

import logging
from typing import Any

from .types import CiteEntry, CiteSpan

logger = logging.getLogger(__name__)


class DefaultCiteAnnotator:
    """Cite annotator that piggybacks on the grounding infrastructure.

    Args:
        entity_trie:  Optional EntityTrie for ENTITY claim extraction.
        extractors:   Override the default ClaimExtractor chain.
    """

    def __init__(
        self,
        entity_trie: Any | None = None,
        extractors: list[Any] | None = None,
    ) -> None:
        self._entity_trie = entity_trie
        self._extractors = extractors

    def annotate(
        self,
        answer: str,
        tool_sources: dict[str, Any],
    ) -> tuple[list[CiteSpan], list[CiteEntry]]:
        """Return (spans, entries) for the final answer.

        Spans are ordered by start offset; entries are deduplicated by
        (tool_name, matched_text) and ordered by cite-N assignment order.
        """
        from ..runtime.validation import (
            extract_claims_from_answer,
            match_claim_sources,
            _default_extractors,
        )

        if not answer or not tool_sources:
            return [], []

        extractors = self._extractors or _default_extractors(self._entity_trie)
        claims = extract_claims_from_answer(answer, extractors=extractors)

        # cite_key → (source_id, tool_name, matched_text)
        cite_registry: dict[str, tuple[str, str, str]] = {}
        counter = 0
        spans: list[CiteSpan] = []

        from ..utils.numbers import (
            canonical_number_claim_value,
            iter_number_spans_in_text,
        )

        for claim in claims:
            matched_keys = match_claim_sources(claim, tool_sources)
            if not matched_keys:
                continue

            # NUMBER: claim.value 无千分位；原文可有「2,000.00」。用
            # iter_number_spans_in_text + canonical_number_claim_value 对齐。
            span_locations: list[tuple[int, int, str]] = []
            if claim.type == "NUMBER":
                for (
                    start,
                    end,
                    raw_text,
                    numeric,
                    _,
                ) in iter_number_spans_in_text(answer):
                    if canonical_number_claim_value(numeric) != claim.value:
                        continue
                    span_locations.append((start, end, raw_text))
            else:
                value = claim.value
                search_start = 0
                while True:
                    idx = answer.find(value, search_start)
                    if idx == -1:
                        break
                    span_end = idx + len(value)
                    span_locations.append((idx, span_end, value))
                    search_start = span_end

            for idx, span_end, matched_text in span_locations:
                for key in matched_keys:
                    tpref = key.startswith("tool_")
                    tool_name = key[len("tool_"):] if tpref else key
                    cite_key = f"{tool_name}::{claim.value}"
                    if cite_key not in cite_registry:
                        counter += 1
                        source_id = f"cite-{counter}"
                        cite_registry[cite_key] = (
                            source_id,
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
