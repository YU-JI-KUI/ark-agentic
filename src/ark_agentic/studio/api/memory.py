"""
Studio Memory API

Provides listing (grouped by user), content retrieval, and content editing.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from ark_agentic.api.deps import get_registry
from ark_agentic.core.memory.manager import MemoryManager
from ark_agentic.studio.services.auth import StudioPrincipal, require_studio_roles, require_studio_user


def _user_id_from_user_memory_rel_path(file_path: str) -> str | None:
    """If ``file_path`` is ``{user_id}/MEMORY.md`` under workspace, return ``user_id``."""
    norm = file_path.replace("\\", "/").strip("/")
    parts = norm.split("/")
    if len(parts) == 2 and parts[1] == "MEMORY.md" and parts[0] and not parts[0].startswith((".", "_")):
        return parts[0]
    return None


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

    global_mem = _file_item(base / "MEMORY.md", "", "memory", base)
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
            user_mem = _file_item(user_dir / "MEMORY.md", user_id, "memory", base)
            if user_mem:
                files.append(user_mem)

    return files


async def _merge_db_memory_items(
    mm: MemoryManager,
    files: list[MemoryFileItem],
) -> list[MemoryFileItem]:
    """Append repository-backed user rows that have no on-disk MEMORY.md."""
    seen = {f.file_path for f in files}
    out = list(files)
    for uid in await mm.list_user_ids():
        rel = f"{uid}/MEMORY.md"
        if rel in seen:
            continue
        seen.add(rel)
        text = await mm.read_memory(uid)
        out.append(
            MemoryFileItem(
                user_id=uid,
                file_path=rel,
                file_type="memory",
                size_bytes=len(text.encode("utf-8")),
                modified_at=None,
            )
        )
    return out


# ── Path resolution (shared by GET / PUT) ───────────────────────────


def _resolve_memory_path(workspace: Path, file_path: str) -> Path:
    """Resolve a relative file_path to an absolute path with traversal guard."""
    resolved = (workspace / file_path).resolve()
    if not str(resolved).startswith(str(workspace.resolve())):
        raise HTTPException(status_code=403, detail="Path traversal denied")
    return resolved


def _get_workspace_and_manager(agent_id: str) -> tuple[Path, MemoryManager]:
    registry = get_registry()
    try:
        runner = registry.get(agent_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")
    mm = runner.memory_manager
    if mm is None:
        raise HTTPException(status_code=404, detail="Memory not enabled for this agent")
    return Path(mm.config.workspace_dir), mm


def _get_workspace(agent_id: str) -> Path:
    ws, _mm = _get_workspace_and_manager(agent_id)
    return ws


router = APIRouter(dependencies=[Depends(require_studio_user)])


# ── Endpoints ───────────────────────────────────────────────────────


@router.get("/agents/{agent_id}/memory/files", response_model=MemoryFilesResponse)
async def list_memory_files(agent_id: str):
    """List all discoverable memory files for this agent, grouped by user."""
    registry = get_registry()
    try:
        runner = registry.get(agent_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")

    mm = runner.memory_manager
    if mm is None:
        return MemoryFilesResponse(files=[])

    workspace = Path(mm.config.workspace_dir)
    files: list[MemoryFileItem] = _scan_memory_files(workspace) if workspace.is_dir() else []
    files = await _merge_db_memory_items(mm, files)
    files.sort(key=lambda x: x.file_path)
    return MemoryFilesResponse(files=files)


@router.get("/agents/{agent_id}/memory/content")
async def get_memory_content(
    agent_id: str,
    file_path: str = Query(..., description="Relative file path within workspace"),
    user_id: str = Query("", description="User ID scope; empty for global files"),
):
    """Read raw content of a memory file."""
    workspace, mm = _get_workspace_and_manager(agent_id)
    uid = _user_id_from_user_memory_rel_path(file_path)
    if uid:
        content = await mm.read_memory(uid)
        return PlainTextResponse(content=content, media_type="text/plain; charset=utf-8")
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
    _: StudioPrincipal = Depends(require_studio_roles("admin", "editor")),
):
    """Write content to a memory file."""
    workspace, mm = _get_workspace_and_manager(agent_id)
    uid = _user_id_from_user_memory_rel_path(file_path)
    if uid:
        body = await request.body()
        await mm.overwrite(uid, body.decode("utf-8"))
        return {"status": "saved"}
    resolved = _resolve_memory_path(workspace, file_path)
    if not resolved.is_file():
        raise HTTPException(status_code=404, detail=f"File not found: {file_path}")
    body = await request.body()
    resolved.write_text(body.decode("utf-8"), encoding="utf-8")
    return {"status": "saved"}
