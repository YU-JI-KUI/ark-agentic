"""Backward-compat shim — real implementations have moved.

New code should import directly from the canonical locations:
  - ark_agentic.core.session_format  — JSONL types, codec, RawJsonlValidationError
  - ark_agentic.core.storage.repository.file._lock  — FileLock (file-backend only)
  - ark_agentic.core.storage.entries  — SessionStoreEntry
"""

from .session_format import (  # noqa: F401
    SESSION_VERSION,
    RawJsonlValidationError,
    SessionHeader,
    MessageEntry,
    serialize_tool_call,
    deserialize_tool_call,
    serialize_tool_result,
    deserialize_tool_result,
    serialize_message,
    deserialize_message,
)
from .storage.repository.file._lock import FileLock  # noqa: F401
from .storage.entries import SessionStoreEntry  # noqa: F401

# Legacy constants that lived alongside FileLock
LOCK_TIMEOUT_MS = 10_000
LOCK_POLL_INTERVAL_MS = 25
LOCK_STALE_MS = 30_000
