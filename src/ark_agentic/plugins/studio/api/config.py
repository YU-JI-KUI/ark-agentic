"""Studio config endpoints — read-only, infra-derived configuration for the SPA."""

from __future__ import annotations

from fastapi import APIRouter

from ark_agentic.core.observability import resolve_trace_link_template

router = APIRouter()


@router.get("/config/trace-link")
def get_trace_link_config() -> dict[str, object]:
    """Return the trace-UI URL template (with ``{trace_id}`` placeholder), or None.

    Frontend caches this once on app load; per-row link rendering is pure
    string substitution client-side.
    """
    template = resolve_trace_link_template()
    return {"enabled": template is not None, "template": template}
