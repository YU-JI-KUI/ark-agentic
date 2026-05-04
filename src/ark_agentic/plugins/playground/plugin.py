"""PlaygroundPlugin — bundled landing/demo HTML + readme + wiki + /static.

Optional plugin shipped with the project for the demo experience. Production
deployments that don't want the demo simply omit it from PLUGINS.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from fastapi.staticfiles import StaticFiles

from ...core.plugin import BasePlugin
from . import routes

logger = logging.getLogger(__name__)

_STATIC_DIR = Path(__file__).parent / "static"


class PlaygroundPlugin(BasePlugin):
    name = "playground"

    def is_enabled(self) -> bool:
        # Default on — playground is harmless if its files are absent.
        return os.getenv("ENABLE_PLAYGROUND", "true").lower() in ("true", "1")

    def install_routes(self, app: Any) -> None:
        if _STATIC_DIR.is_dir():
            app.mount(
                "/static",
                StaticFiles(directory=str(_STATIC_DIR)),
                name="static",
            )
        else:
            logger.info("Playground static dir absent, /static mount skipped")
        app.include_router(routes.router)
