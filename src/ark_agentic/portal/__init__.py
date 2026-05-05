"""ark-agentic framework portal — landing site, agent demo pages,
README + wiki rendering, securities mock-mode admin probe.

This package is **framework-internal**: it ships in the source tree so
running ``ark_agentic.app`` from a checkout serves the project intro and
the bundled per-agent demos, but it is **excluded from the published
wheel** (see ``pyproject.toml``). End-user projects that install
``ark-agentic`` from PyPI never see these pages — they get the
APIPlugin's default chat demo at ``/`` instead.

``Portal`` implements ``Lifecycle`` directly (not ``Plugin``) — it is
not user-selectable, it is the framework's own face. Bootstrap drives
it through the same install_routes / start / stop hooks as every other
component, so ``app.py`` does not need a special-case mount call.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..core.protocol.lifecycle import BaseLifecycle

_STATIC_DIR = Path(__file__).parent / "static"

__all__ = ["Portal"]


class Portal(BaseLifecycle):
    """Framework-internal landing + demo site, registered as a Lifecycle
    component so Bootstrap drives it uniformly with everything else."""

    name = "portal"

    def install_routes(self, app: Any) -> None:
        from fastapi.staticfiles import StaticFiles

        from .routes import router

        if _STATIC_DIR.is_dir():
            app.mount(
                "/static",
                StaticFiles(directory=str(_STATIC_DIR)),
                name="portal-static",
            )
        app.include_router(router)
