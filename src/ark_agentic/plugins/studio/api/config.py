"""Studio config endpoints.

These endpoints expose read-only, infra-derived configuration for the SPA.
"""

from __future__ import annotations

from fastapi import APIRouter

from ark_agentic.core.observability import resolve_trace_link_template
from ark_agentic.core.utils.env import env_flag

router = APIRouter()


@router.get("/config/trace-link")
def get_trace_link_config() -> dict[str, object]:
    """Return the trace-UI URL template, or None.

    Frontend caches this once on app load; per-row link rendering is pure
    string substitution client-side. The template includes a ``{trace_id}``
    placeholder.
    """
    template = resolve_trace_link_template()
    return {"enabled": template is not None, "template": template}


@router.get("/config/features")
def get_studio_features_config() -> dict[str, bool]:
    """Return feature flags that affect Studio navigation and pages."""
    return {"mcp_enabled": env_flag("ENABLE_MCP", default=False)}
