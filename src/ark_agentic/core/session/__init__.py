"""Session subsystem — manager, on-disk format, compaction, history merge.

``manager.py``       — ``SessionManager`` orchestrator (per-agent).
``format.py``        — JSONL transcript codec + ``RawJsonlValidationError``.
``compaction.py``    — context window compaction (token estimation, LLM summary).
``history_merge.py`` — merging externally-supplied history into the session.
"""

from .compaction import (
    CompactionConfig,
    CompactionResult,
    ContextCompactor,
    LLMSummarizer,
    SummarizerProtocol,
    estimate_message_tokens,
    estimate_tokens,
)
from .format import (
    SESSION_VERSION,
    MessageEntry,
    RawJsonlValidationError,
    SessionHeader,
    deserialize_message,
    deserialize_tool_call,
    deserialize_tool_result,
    serialize_message,
    serialize_tool_call,
    serialize_tool_result,
)
from .manager import SessionManager

__all__ = [
    "SESSION_VERSION",
    "CompactionConfig",
    "CompactionResult",
    "ContextCompactor",
    "LLMSummarizer",
    "MessageEntry",
    "RawJsonlValidationError",
    "SessionHeader",
    "SessionManager",
    "SummarizerProtocol",
    "deserialize_message",
    "deserialize_tool_call",
    "deserialize_tool_result",
    "estimate_message_tokens",
    "estimate_tokens",
    "serialize_message",
    "serialize_tool_call",
    "serialize_tool_result",
]
