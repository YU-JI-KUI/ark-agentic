"""Cite data types — CiteSpan (inline) and CiteEntry (summary)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CiteSpan:
    """Single citation span emitted per matched claim (inline, post-answer)."""

    source_id: str       # e.g. "cite-1"
    tool_name: str       # e.g. "customer_info"
    start: int           # char offset within answer
    end: int
    matched_text: str    # verbatim text that triggered the citation


@dataclass
class CiteEntry:
    """Citation entry in the final citation_list summary event."""

    source_id: str       # e.g. "cite-1"
    tool_name: str       # e.g. "customer_info"
    matched_text: str
