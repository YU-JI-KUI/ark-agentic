"""Studio MCP API."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ark_agentic.core.mcp import MCPManager
from ark_agentic.core.utils.env import get_agents_root
from ark_agentic.plugins.studio.services import mcp_service
from ark_agentic.plugins.studio.services.auth import (
    StudioPrincipal,
    require_studio_roles,
    require_studio_user,
)

router = APIRouter(dependencies=[Depends(require_studio_user)])


class MCPToolMeta(BaseModel):
    name: str
    registered_name: str
    description: str = ""
    enabled: bool = True
    input_schema: dict[str, Any] = Field(default_factory=dict)
    parameter_count: int = 0


class MCPServerMeta(BaseModel):
    id: str
    name: str
    description: str = ""
    transport: str = ""
    enabled: bool = True
    required: bool = False
    timeout: float = 30.0
    url: str | None = None
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    headers: dict[str, str] = Field(default_factory=dict)
    status: str = "unknown"
    error: str | None = None
    total_tools: int = 0
    enabled_tools: int = 0
    tools: list[MCPToolMeta] = Field(default_factory=list)


class MCPListResponse(BaseModel):
    servers: list[MCPServerMeta]


class MCPServerCreateRequest(BaseModel):
    id: str = Field(..., min_length=1)
    name: str = ""
    description: str = ""
    transport: str = "streamable_http"
    enabled: bool = True
    required: bool = False
    timeout: float = 30.0
    url: str | None = None
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    headers: dict[str, str] = Field(default_factory=dict)


class MCPServerUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    transport: str | None = None
    enabled: bool | None = None
    required: bool | None = None
    timeout: float | None = None
    url: str | None = None
    command: str | None = None
    args: list[str] | None = None
    env: dict[str, str] | None = None
    headers: dict[str, str] | None = None


class MCPEnabledPatch(BaseModel):
    enabled: bool


@router.get("/agents/{agent_id}/mcp", response_model=MCPListResponse)
async def list_mcp(agent_id: str, request: Request):
    _ensure_agent_exists(request, agent_id)
    manager = _get_mcp_manager(request)
    with _service_errors(agent_id):
        raw_servers = mcp_service.list_servers(get_agents_root(), agent_id)
    return MCPListResponse(
        servers=_merge_raw_and_runtime(raw_servers, manager.snapshot(agent_id))
    )


@router.post("/agents/{agent_id}/mcp/servers", response_model=MCPServerMeta)
async def create_mcp_server(
    agent_id: str,
    req: MCPServerCreateRequest,
    request: Request,
    _: StudioPrincipal = Depends(require_studio_roles("admin", "editor")),
):
    with _service_errors(agent_id, conflict_server_id=req.id):
        created = mcp_service.create_server(
            get_agents_root(),
            agent_id,
            req.id,
            name=req.name,
            description=req.description,
            transport=req.transport,
            enabled=req.enabled,
            required=req.required,
            timeout=req.timeout,
            url=req.url,
            command=req.command,
            args=req.args,
            env=req.env,
            headers=req.headers,
        )

    manager = _get_mcp_manager(request)
    await _reload_agent_config(manager, agent_id)
    return _get_server_or_404(manager, agent_id, str(created["id"]))


@router.put(
    "/agents/{agent_id}/mcp/servers/{server_id}",
    response_model=MCPServerMeta,
)
async def replace_mcp_server(
    agent_id: str,
    server_id: str,
    req: MCPServerUpdateRequest,
    request: Request,
    _: StudioPrincipal = Depends(require_studio_roles("admin", "editor")),
):
    with _service_errors(agent_id, server_id=server_id):
        mcp_service.update_server(
            get_agents_root(),
            agent_id,
            server_id,
            name=req.name,
            description=req.description,
            transport=req.transport,
            enabled=req.enabled,
            required=req.required,
            timeout=req.timeout,
            url=req.url,
            command=req.command,
            args=req.args,
            env=req.env,
            headers=req.headers,
        )

    manager = _get_mcp_manager(request)
    await _reload_agent_config(manager, agent_id)
    return _get_server_or_404(manager, agent_id, server_id)


@router.patch(
    "/agents/{agent_id}/mcp/servers/{server_id}",
    response_model=MCPServerMeta,
)
async def update_mcp_server(
    agent_id: str,
    server_id: str,
    patch: MCPEnabledPatch,
    request: Request,
    _: StudioPrincipal = Depends(require_studio_roles("admin", "editor")),
):
    with _service_errors(agent_id, server_id=server_id):
        mcp_service.update_server_enabled(
            get_agents_root(),
            agent_id,
            server_id,
            patch.enabled,
        )

    manager = _get_mcp_manager(request)
    await _reload_agent_config(manager, agent_id)
    return _get_server_or_404(manager, agent_id, server_id)


@router.patch(
    "/agents/{agent_id}/mcp/servers/{server_id}/tools/{tool_name}",
    response_model=MCPServerMeta,
)
async def update_mcp_tool(
    agent_id: str,
    server_id: str,
    tool_name: str,
    patch: MCPEnabledPatch,
    request: Request,
    _: StudioPrincipal = Depends(require_studio_roles("admin", "editor")),
):
    with _service_errors(agent_id, server_id=server_id):
        mcp_service.update_tool_enabled(
            get_agents_root(),
            agent_id,
            server_id,
            tool_name,
            patch.enabled,
        )

    manager = _get_mcp_manager(request)
    await _reload_agent_config(manager, agent_id)
    return _get_server_or_404(manager, agent_id, server_id)


@router.delete("/agents/{agent_id}/mcp/servers/{server_id}")
async def delete_mcp_server(
    agent_id: str,
    server_id: str,
    request: Request,
    _: StudioPrincipal = Depends(require_studio_roles("admin", "editor")),
):
    with _service_errors(agent_id, server_id=server_id):
        mcp_service.delete_server(get_agents_root(), agent_id, server_id)

    manager = _get_mcp_manager(request)
    await _reload_agent_config(manager, agent_id)
    return {"status": "deleted", "server_id": server_id}


def _get_mcp_manager(request: Request) -> MCPManager:
    ctx = getattr(request.app.state, "ctx", None)
    manager = getattr(ctx, "mcp", None) if ctx is not None else None
    if manager is None:
        raise HTTPException(
            status_code=503,
            detail="MCP manager is not initialised",
        )
    return manager


def _ensure_agent_exists(request: Request, agent_id: str) -> None:
    ctx = getattr(request.app.state, "ctx", None)
    registry = (
        getattr(ctx, "agent_registry", None)
        if ctx is not None else None
    )
    if registry is None:
        return
    if agent_id not in registry.list_ids():
        raise HTTPException(
            status_code=404,
            detail=f"Agent not found: {agent_id}",
        )


async def _reload_agent_config(
    manager: MCPManager,
    agent_id: str,
) -> None:
    try:
        await manager.reload_agent_config(agent_id)
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail=f"Agent not found: {agent_id}",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@contextmanager
def _service_errors(
    agent_id: str,
    *,
    server_id: str | None = None,
    conflict_server_id: str | None = None,
) -> Iterator[None]:
    try:
        yield
    except FileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=f"Agent not found: {agent_id}",
        )
    except FileExistsError:
        raise HTTPException(
            status_code=409,
            detail=f"MCP server already exists: {conflict_server_id}",
        )
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail=f"MCP server not found: {server_id}",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


def _get_server_or_404(
    manager: MCPManager,
    agent_id: str,
    server_id: str,
) -> MCPServerMeta:
    try:
        raw_server = mcp_service.get_server(
            get_agents_root(),
            agent_id,
            server_id,
        )
    except (FileNotFoundError, KeyError):
        raw_server = None
    runtime_by_id = {
        item["id"]: item
        for item in manager.snapshot(agent_id)
    }
    if raw_server is not None:
        return MCPServerMeta(
            **_merge_one_server(raw_server, runtime_by_id.get(server_id))
        )
    runtime = runtime_by_id.get(server_id)
    if runtime is not None:
        return MCPServerMeta(**runtime)
    raise HTTPException(
        status_code=404,
        detail=f"MCP server not found: {server_id}",
    )


def _merge_raw_and_runtime(
    raw_servers: list[dict[str, Any]],
    runtime_servers: list[dict[str, Any]],
) -> list[MCPServerMeta]:
    runtime_by_id = {server["id"]: server for server in runtime_servers}
    result = [
        MCPServerMeta(
            **_merge_one_server(raw, runtime_by_id.pop(raw["id"], None))
        )
        for raw in raw_servers
        if raw.get("id")
    ]
    result.extend(MCPServerMeta(**server) for server in runtime_by_id.values())
    return result


def _merge_one_server(
    raw: dict[str, Any],
    runtime: dict[str, Any] | None,
) -> dict[str, Any]:
    merged = dict(runtime or {})
    merged.update({
        "id": raw.get("id"),
        "name": raw.get("name") or raw.get("id"),
        "description": raw.get("description") or "",
        "transport": raw.get("transport") or "",
        "enabled": raw.get("enabled", True),
        "required": raw.get("required", False),
        "timeout": raw.get("timeout", 30.0) or 30.0,
        "url": raw.get("url"),
        "command": raw.get("command"),
        "args": raw.get("args") or [],
        "env": raw.get("env") or {},
        "headers": raw.get("headers") or {},
    })
    return merged
