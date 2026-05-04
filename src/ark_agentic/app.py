"""ark-agentic FastAPI entry point.

Composition root only: wires the default Lifecycle component list into a
``Bootstrap`` and lets it drive everything (init / install_routes /
start / stop). All actual work — schema, agents, tracing, HTTP routes,
middleware — lives in components, not here.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv

load_dotenv()

# Global logging setup must happen before any logger.getLogger callers
# below would otherwise inherit the root config.
_log_level = getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)
logging.basicConfig(
    level=_log_level,
    format="%(asctime)s %(levelname)-5s %(name)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    force=True,
)

from fastapi import FastAPI

from ark_agentic.bootstrap import DEFAULT_PLUGINS
from ark_agentic.core.bootstrap import Bootstrap
from ark_agentic.plugins.api.context import AppContext

logger = logging.getLogger(__name__)
_bootstrap = Bootstrap(DEFAULT_PLUGINS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    ctx = AppContext()
    await _bootstrap.start(ctx)
    app.state.ctx = ctx
    try:
        yield
    finally:
        await _bootstrap.stop()


app = FastAPI(
    title="Ark-Agentic API",
    description="统一 Agent API",
    version="0.1.0",
    lifespan=lifespan,
)

# Framework-only showcase site (landing / agent demos / README+wiki).
# Mounted **before** plugin routes so this repo's home page wins over
# the APIPlugin's default ``/`` chat demo. The showcase package is
# excluded from the published wheel — third-party deployments install
# this code path don't have it and fall through to the plugin default.
from ark_agentic.showcase import setup_showcase
setup_showcase(app)

_bootstrap.install_routes(app)


def main() -> None:
    import uvicorn

    uvicorn.run(
        "ark_agentic.app:app",
        host=os.getenv("API_HOST", "0.0.0.0"),
        port=int(os.getenv("API_PORT", "8080")),
        reload=False,
        log_level=os.getenv("LOG_LEVEL", "info").lower(),
    )


if __name__ == "__main__":
    main()
