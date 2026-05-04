"""ark-agentic framework showcase — landing site, agent demo pages,
README + wiki rendering, securities mock-mode admin probe.

This package is **framework-internal**: it ships in the source tree so
running ``ark_agentic.app`` from a checkout serves the project intro and
the bundled per-agent demos, but it is **excluded from the published
wheel** (see ``pyproject.toml``). End-user projects that install
``ark-agentic`` from PyPI never see these pages — they get the
APIPlugin's default chat demo at ``/`` instead.

This package is *not* a Plugin. It implements no Lifecycle methods.
``app.py`` mounts it via ``setup_showcase(app)`` directly, before the
Bootstrap routes are installed, so its ``/`` handler wins over the
APIPlugin's default landing in framework deployments.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from .routes import router

if TYPE_CHECKING:
    from fastapi import FastAPI

__all__ = ["setup_showcase"]


def setup_showcase(app: "FastAPI") -> None:
    """Mount the showcase ``/static`` assets and HTTP routes."""
    from fastapi.staticfiles import StaticFiles

    static_dir = Path(__file__).parent / "static"
    if static_dir.is_dir():
        app.mount(
            "/static",
            StaticFiles(directory=str(static_dir)),
            name="showcase-static",
        )
    app.include_router(router)
