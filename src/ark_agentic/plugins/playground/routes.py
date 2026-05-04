"""Playground HTTP routes — landing page, demo agent UIs, README, wiki.

These endpoints exist for the bundled demo experience; production agent
deployments without the playground simply omit ``PlaygroundPlugin`` from
their PLUGINS list.
"""

from __future__ import annotations

import json as _json
import logging
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response

logger = logging.getLogger(__name__)

router = APIRouter(tags=["playground"])

_STATIC_DIR = Path(__file__).parent / "static"
_REPO_ROOT = Path(__file__).resolve().parents[3]
_README_PATH = _REPO_ROOT / "README.md"
_WIKI_ROOT = _REPO_ROOT / "repowiki"


@router.get("/", include_in_schema=False)
async def root():
    """项目主页。home.html 缺失时 fallback 到保险 Demo，避免 500。"""
    page = _STATIC_DIR / "home.html"
    if page.is_file():
        return FileResponse(str(page), media_type="text/html")
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/insurance")


@router.get("/insurance", include_in_schema=False)
async def insurance_page():
    page = _STATIC_DIR / "insurance.html"
    if page.is_file():
        return FileResponse(str(page), media_type="text/html")
    return {"message": "insurance page not found"}


@router.get("/securities", include_in_schema=False)
async def securities_page():
    page = _STATIC_DIR / "securities.html"
    if page.is_file():
        return FileResponse(str(page), media_type="text/html")
    return {"message": "securities page not found"}


@router.get("/api/readme", include_in_schema=False)
async def get_readme():
    """返回项目根 README.md 纯文本，供 landing 页 Docs Tab 客户端渲染。"""
    if _README_PATH.is_file():
        return PlainTextResponse(
            _README_PATH.read_text(encoding="utf-8"),
            media_type="text/markdown; charset=utf-8",
        )
    return Response(status_code=404, content="README.md not found")


@router.get("/api/wiki/tree", include_in_schema=False)
async def get_wiki_tree():
    """返回 repowiki 两种语言的目录树，按 repowiki-metadata.json 的 wiki_items 顺序排列。"""

    def load_order_map(lang: str) -> dict:
        """返回 {name: order_index}，顺序来自 wiki_items 列表索引。"""
        meta_path = _WIKI_ROOT / lang / "meta" / "repowiki-metadata.json"
        if not meta_path.is_file():
            return {}
        with open(meta_path, encoding="utf-8") as f:
            meta = _json.load(f)
        catalog_by_id = {c["id"]: c for c in meta.get("wiki_catalogs", [])}
        order_map: dict = {}
        for idx, item in enumerate(meta.get("wiki_items", [])):
            catalog = catalog_by_id.get(item.get("catalog_id", ""))
            if catalog:
                name = catalog.get("name", "")
                if name and name not in order_map:
                    order_map[name] = idx
        return order_map

    def build_tree(base: Path, rel: Path, order_map: dict) -> list:
        target = base / rel
        if not target.is_dir():
            return []

        def sort_key(p: Path) -> tuple:
            display = p.stem if p.suffix == ".md" else p.name
            return (order_map.get(display, 9999), p.name.lower())

        items = []
        for entry in sorted(target.iterdir(), key=sort_key):
            entry_rel = rel / entry.name
            if entry.is_dir():
                children = build_tree(base, entry_rel, order_map)
                if children:
                    items.append({"type": "dir", "name": entry.name, "path": str(entry_rel).replace("\\", "/"), "children": children})
            elif entry.suffix == ".md":
                items.append({"type": "file", "name": entry.stem, "path": str(entry_rel).replace("\\", "/")})
        return items

    result = {}
    for lang in ("zh", "en"):
        content_dir = _WIKI_ROOT / lang / "content"
        order_map = load_order_map(lang)
        result[lang] = build_tree(content_dir, Path("."), order_map) if content_dir.is_dir() else []
    return JSONResponse(result)


@router.get("/api/wiki/{lang}/{path:path}", include_in_schema=False)
async def get_wiki_page(lang: str, path: str):
    """返回指定 wiki 页面的 Markdown 内容。"""
    if lang not in ("zh", "en"):
        return Response(status_code=400, content="invalid lang")
    file_path = _WIKI_ROOT / lang / "content" / path
    if not file_path.is_file() or file_path.suffix != ".md":
        return Response(status_code=404, content="not found")
    # 安全检查：防止路径穿越
    try:
        file_path.resolve().relative_to((_WIKI_ROOT / lang / "content").resolve())
    except ValueError:
        return Response(status_code=403, content="forbidden")
    return PlainTextResponse(file_path.read_text(encoding="utf-8"), media_type="text/markdown; charset=utf-8")


@router.get("/api/admin/securities-mock", include_in_schema=False)
async def get_securities_mock_mode():
    """返回服务级默认 mock 状态（来自 SECURITIES_SERVICE_MOCK 环境变量，只读）。"""
    from ...agents.securities.tools.service.mock_mode import get_mock_mode
    return {"mock": get_mock_mode()}
