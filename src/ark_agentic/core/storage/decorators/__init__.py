"""Repository decorators — orthogonal cross-cutting concerns.

Currently houses caching wrappers; future use cases (metrics, tracing,
audit) can plug in here without touching either the Protocol or the
backends.
"""

from .session import CachedSessionRepository

__all__ = ["CachedSessionRepository"]
