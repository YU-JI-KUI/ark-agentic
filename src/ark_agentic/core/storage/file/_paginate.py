"""In-memory pagination helper for file-backend list endpoints.

The file backends materialise the full result set in memory and slice
it; SQL backends push limit/offset into the query directly, so this
helper is local to ``file/``.
"""

from __future__ import annotations

from typing import TypeVar

T = TypeVar("T")


def paginate(items: list[T], limit: int | None, offset: int) -> list[T]:
    start = max(offset, 0)
    if limit is None:
        return items[start:]
    return items[start:start + limit]
