"""Storage protocols - typing.Protocol definitions.

业务代码只依赖此包；任何后端实现都必须满足这些 Protocol。
"""

from .memory import MemoryRepository
from .session import SessionRepository

__all__ = [
    "MemoryRepository",
    "SessionRepository",
]
