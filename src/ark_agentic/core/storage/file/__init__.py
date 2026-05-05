"""File backend — Tier 0 default storage implementations.

Each ``FileXxxRepository`` owns its own file I/O. JSONL serialisation
primitives that the SQLite raw-transcript path also reuses live in
``core.session.format``.
"""

from .memory import FileMemoryRepository
from .session import FileSessionRepository

__all__ = [
    "FileMemoryRepository",
    "FileSessionRepository",
]
