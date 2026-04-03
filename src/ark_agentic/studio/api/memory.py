"""
Studio Memory API

Provides listing (grouped by user), content retrieval, and content editing.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from ark_agentic.api.deps import get_registry
from ark_agentic.core.paths import get_memory_base_dir

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Models ──────────────────────────────────────────────────────────

class MemoryFileItem(BaseModel):
    user_id: str
    file_path: str
    file_type: str
    size_bytes: int
    modified_at: str | None


class MemoryFilesResponse(BaseModel):
    files: list[MemoryFileItem]


# ── Helpers ─────────────────────────────────────────────────────────

def _file_item(path: Path, user_id: str, file_type: str, rel_to: Path) -> MemoryFileItem | None:
    if not path.is_file():
        return None
    stat = path.stat()
    return MemoryFileItem(
        user_id=user_id,
        file_path=str(path.relative_to(rel_to)).replace("\\", "/"),
        file_type=file_type,
        size_bytes=stat.st_size,
        modified_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
    )


def _scan_memory_files(workspace_dir: Path) -> list[MemoryFileItem]:
    """Discover MEMORY.md files within an agent workspace and global profiles."""
    files: list[MemoryFileItem] = []
    base = workspace_dir

    global_mem = _file_item(base / "MEMORY.md", "", "agent_memory", base)
    if global_mem:
        files.append(global_mem)

    memory_subdir = base / "memory"
    if memory_subdir.is_dir():
        for md in sorted(memory_subdir.glob("*.md")):
            item = _file_item(md, "", "knowledge", base)
            if item:
                files.append(item)

    if base.is_dir():
        for user_dir in sorted(base.iterdir()):
            if not user_dir.is_dir() or user_dir.name.startswith((".", "_")):
                continue
            user_id = user_dir.name
            user_mem = _file_item(user_dir / "MEMORY.md", user_id, "agent_memory", base)
            if user_mem:
                files.append(user_mem)

    profiles_dir = get_memory_base_dir() / "_profiles"
    if profiles_dir.is_dir():
        for profile_dir in sorted(profiles_dir.iterdir()):
            if not profile_dir.is_dir():
                continue
            uid = profile_dir.name
            profile_file = _file_item(profile_dir / "MEMORY.md", uid, "profile", profiles_dir.parent)
            if profile_file:
                files.append(profile_file)

    return files


# ── Path resolution (shared by GET / PUT) ───────────────────────────

def _resolve_memory_path(workspace: Path, file_path: str) -> Path:
    """Resolve a relative file_path to an absolute path with traversal guard."""
    if file_path.startswith("_profiles/"):
        resolved = get_memory_base_dir() / file_path
    else:
        resolved = workspace / file_path
    resolved = resolved.resolve()
    allowed = [workspace.resolve(), get_memory_base_dir().resolve()]
    if not any(str(resolved).startswith(str(r)) for r in allowed):
        raise HTTPException(status_code=403, detail="Path traversal denied")
    return resolved


def _get_workspace(agent_id: str) -> Path:
    registry = get_registry()
    try:
        runner = registry.get(agent_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")
    mm = runner._memory_manager
    if mm is None:
        raise HTTPException(status_code=404, detail="Memory not enabled for this agent")
    return Path(mm.config.workspace_dir)


# ── Endpoints ───────────────────────────────────────────────────────

@router.get("/agents/{agent_id}/memory/files", response_model=MemoryFilesResponse)
async def list_memory_files(agent_id: str):
    """List all discoverable memory files for this agent, grouped by user."""
    registry = get_registry()
    try:
        runner = registry.get(agent_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")

    mm = runner._memory_manager
    if mm is None:
        return MemoryFilesResponse(files=[])

    workspace = Path(mm.config.workspace_dir)
    if not workspace.is_dir():
        return MemoryFilesResponse(files=[])

    return MemoryFilesResponse(files=_scan_memory_files(workspace))


@router.get("/agents/{agent_id}/memory/content")
async def get_memory_content(
    agent_id: str,
    file_path: str = Query(..., description="Relative file path within workspace"),
    user_id: str = Query("", description="User ID scope; empty for global files"),
):
    """Read raw content of a memory file."""
    workspace = _get_workspace(agent_id)
    resolved = _resolve_memory_path(workspace, file_path)

    if not resolved.is_file():
        raise HTTPException(status_code=404, detail=f"File not found: {file_path}")

    content = resolved.read_text(encoding="utf-8")
    return PlainTextResponse(content=content, media_type="text/plain; charset=utf-8")


@router.put("/agents/{agent_id}/memory/content")
async def put_memory_content(
    agent_id: str,
    request: Request,
    file_path: str = Query(..., description="Relative file path within workspace"),
    user_id: str = Query("", description="User ID scope; empty for global files"),
):
    """Write content to a memory file."""
    workspace = _get_workspace(agent_id)
    resolved = _resolve_memory_path(workspace, file_path)

    if not resolved.is_file():
        raise HTTPException(status_code=404, detail=f"File not found: {file_path}")

    body = await request.body()
    resolved.write_text(body.decode("utf-8"), encoding="utf-8")

    try:
        runner = get_registry().get(agent_id)
        runner.mark_memory_dirty()
    except KeyError:
        pass

    return {"status": "saved"}
