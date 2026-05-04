"""Default ark-agentic component list — single source of truth for the
``Bootstrap`` consumer in ``app.py``, CLI scaffolds, and tests.

Order matters:

1. ``AgentsRuntime``       — populates ``ctx.registry`` first so plugins
                              that need agents (e.g. JobsPlugin's
                              proactive-job wiring) can read it.
2. ``APIPlugin``           — installs CORS + chat + /health + middleware,
                              and a default ``/`` chat-demo page.
3. ``NotificationsPlugin`` — populates ``ctx.notifications``.
4. ``JobsPlugin``          — reads ``ctx.notifications`` + ``ctx.registry``.
5. ``StudioPlugin``        — admin console (init runs against its
                              own SQLite engine regardless of DB_TYPE).
6. ``TracingRuntime``      — last so a tracing failure can't block the
                              earlier components from starting / stopping.

Stop order is the reverse, handled by ``Bootstrap.stop``.

Custom hosts (CLI scaffold output, test harnesses) build their own list::

    from ark_agentic.bootstrap import DEFAULT_PLUGINS
    from ark_agentic.core.bootstrap import Bootstrap

    bootstrap = Bootstrap([c for c in DEFAULT_PLUGINS if include(c)])

NOTE: the framework's own showcase site (landing page, agent demos,
README/wiki rendering) is NOT a plugin and not in this list. It lives
under ``ark_agentic.showcase`` and is mounted by ``app.py`` directly via
``setup_showcase(app)`` — excluded from the published wheel.
"""

from __future__ import annotations

from .core.lifecycle import Lifecycle
from .core.runtime.agents import AgentsRuntime
from .core.runtime.tracing import TracingRuntime
from .plugins.api.plugin import APIPlugin
from .plugins.jobs.plugin import JobsPlugin
from .plugins.notifications.plugin import NotificationsPlugin
from .plugins.studio.plugin import StudioPlugin

DEFAULT_PLUGINS: list[Lifecycle] = [
    AgentsRuntime(),
    APIPlugin(),
    NotificationsPlugin(),
    JobsPlugin(),
    StudioPlugin(),
    TracingRuntime(),
]
