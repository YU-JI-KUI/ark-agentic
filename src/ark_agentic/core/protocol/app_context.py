"""AppContext — runtime container populated by Lifecycle components.

``Bootstrap.start()`` walks the registered ``Lifecycle`` components and,
for each one whose ``start()`` returns a non-``None`` value, calls
``setattr(ctx, component.name, value)``. Consumers retrieve those
attributes by name — defensively for optional plugins (they may be
disabled and never publish themselves).

Core lifecycle components publish their state through typed slots
declared here so consumers get static guarantees. Plugins (optional)
still read via ``getattr(ctx, "<name>", None)``; ``core/`` does not
encode plugin names.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..mcp import MCPManager
    from ..runtime.registry import AgentRegistry


class AppContext:
    """Runtime container; core slots are typed, plugin slots are dynamic."""

    agent_registry: "AgentRegistry | None" = None
    mcp: "MCPManager | None" = None
