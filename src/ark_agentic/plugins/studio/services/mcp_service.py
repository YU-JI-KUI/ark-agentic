"""MCP Studio service helpers."""

from __future__ import annotations

import json
import re
import shlex
from pathlib import Path
from typing import Any

from ark_agentic.core.paths import (
    get_agent_config_file,
    resolve_agent_config_file,
)
from ark_agentic.core.utils.env import resolve_agent_dir

_SERVER_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_SUPPORTED_TRANSPORTS = {"stdio", "streamable_http"}


def create_server(
    agents_root: Path,
    agent_id: str,
    server_id: str,
    name: str = "",
    description: str = "",
    transport: str = "streamable_http",
    enabled: bool = True,
    required: bool = False,
    timeout: float = 30.0,
    url: str | None = None,
    command: str | None = None,
    args: list[str] | None = None,
    env: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    data, meta_file = _load_agent_json(
        agents_root,
        agent_id,
        create_if_missing=True,
    )
    server_id = server_id.strip()
    if not server_id or not _SERVER_ID_RE.match(server_id):
        raise ValueError(
            "MCP server id must contain only letters, numbers, "
            "underscore, or hyphen"
        )
    transport = _normalise_transport(transport)
    servers = _get_servers(data, create=True)
    if any(
        isinstance(server, dict)
        and str(server.get("id") or "") == server_id
        for server in servers
    ):
        raise FileExistsError(f"MCP server already exists: {server_id}")

    server: dict[str, Any] = {
        "id": server_id,
        "name": name.strip() or server_id,
        "description": description.strip(),
        "transport": transport,
        "enabled": enabled,
        "required": required,
        "timeout": float(timeout or 30.0),
    }
    if transport == "streamable_http":
        clean_url = (url or "").strip()
        if not clean_url:
            raise ValueError("MCP HTTP server requires url")
        server["url"] = clean_url
        if headers:
            server["headers"] = {str(k): str(v) for k, v in headers.items()}
    else:
        command_parts = _split_shell_words((command or "").strip())
        if not command_parts:
            raise ValueError("MCP stdio server requires command")
        server["command"] = command_parts[0]
        server_args = [*command_parts[1:], *_normalise_args(args or [])]
        if server_args:
            server["args"] = server_args
        if env:
            server["env"] = {str(k): str(v) for k, v in env.items()}

    servers.append(server)
    _write_agent_json(meta_file, data)
    return server


def update_server_enabled(
    agents_root: Path,
    agent_id: str,
    server_id: str,
    enabled: bool,
) -> None:
    data, meta_file = _load_agent_json(agents_root, agent_id)
    server = _find_server(data, server_id)
    server["enabled"] = enabled
    _write_agent_json(meta_file, data)


def update_tool_enabled(
    agents_root: Path,
    agent_id: str,
    server_id: str,
    tool_name: str,
    enabled: bool,
) -> None:
    data, meta_file = _load_agent_json(agents_root, agent_id)
    server = _find_server(data, server_id)
    tools = server.setdefault("tools", {})
    if not isinstance(tools, dict):
        tools = {}
        server["tools"] = tools
    enabled_map = tools.setdefault("enabled", {})
    if not isinstance(enabled_map, dict):
        enabled_map = {}
        tools["enabled"] = enabled_map
    enabled_map[tool_name] = enabled
    _write_agent_json(meta_file, data)


def _load_agent_json(
    agents_root: Path,
    agent_id: str,
    *,
    create_if_missing: bool = False,
) -> tuple[dict[str, Any], Path]:
    agent_dir = resolve_agent_dir(agents_root, agent_id)
    if not agent_dir:
        raise FileNotFoundError(f"Agent not found: {agent_id}")
    write_file = get_agent_config_file(agent_id, create=True)
    read_file = resolve_agent_config_file(
        agent_id,
        legacy_agent_dir=agent_dir,
    )
    if read_file is None:
        if not create_if_missing:
            raise FileNotFoundError(f"agent.json not found for {agent_id}")
        data: dict[str, Any] = {"id": agent_id, "name": agent_id}
        return data, write_file
    data = json.loads(read_file.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("agent.json must contain an object")
    return data, write_file


def _find_server(data: dict[str, Any], server_id: str) -> dict[str, Any]:
    servers = _get_servers(data)
    for server in servers:
        if (
            isinstance(server, dict)
            and str(server.get("id") or "") == server_id
        ):
            return server
    raise KeyError(server_id)


def _get_servers(
    data: dict[str, Any],
    *,
    create: bool = False,
) -> list[Any]:
    mcp = data.get("mcp")
    if mcp is None and create:
        mcp = {}
        data["mcp"] = mcp
    if mcp is None:
        return []
    if not isinstance(mcp, dict):
        raise ValueError("agent.json mcp must be an object")
    servers = mcp.get("servers")
    if servers is None and create:
        servers = []
        mcp["servers"] = servers
    if servers is None:
        return []
    if not isinstance(servers, list):
        raise ValueError("agent.json mcp.servers must be a list")
    return servers


def _normalise_transport(value: str) -> str:
    transport = value.strip().lower().replace("-", "_")
    if transport in {"http", "streamable"}:
        transport = "streamable_http"
    if transport not in _SUPPORTED_TRANSPORTS:
        raise ValueError(f"Unsupported MCP transport: {transport}")
    return transport


def _normalise_args(args: list[str]) -> list[str]:
    result: list[str] = []
    for arg in args:
        result.extend(_split_shell_words(str(arg)))
    return result


def _split_shell_words(value: str) -> list[str]:
    if not value:
        return []
    try:
        return shlex.split(value)
    except ValueError as exc:
        raise ValueError(f"Invalid shell command fragment: {value}") from exc


def _write_agent_json(meta_file: Path, data: dict[str, Any]) -> None:
    meta_file.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
