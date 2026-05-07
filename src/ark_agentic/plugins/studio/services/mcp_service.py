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
    args: list[str] | str | None = None,
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

    server = _build_server(
        server_id=server_id,
        name=name,
        description=description,
        transport=transport,
        enabled=enabled,
        required=required,
        timeout=timeout,
        url=url,
        command=command,
        args=args,
        env=env,
        headers=headers,
    )
    servers.append(server)
    _write_agent_json(meta_file, data)
    return server


def list_servers(
    agents_root: Path,
    agent_id: str,
) -> list[dict[str, Any]]:
    agent_dir = resolve_agent_dir(agents_root, agent_id)
    if not agent_dir:
        raise FileNotFoundError(f"Agent not found: {agent_id}")
    read_file = resolve_agent_config_file(
        agent_id,
        legacy_agent_dir=agent_dir,
    )
    if read_file is None:
        return []
    data = json.loads(read_file.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("agent.json must contain an object")
    return [_public_server(server) for server in _get_servers(data)]


def get_server(
    agents_root: Path,
    agent_id: str,
    server_id: str,
) -> dict[str, Any]:
    data, _ = _load_agent_json(agents_root, agent_id)
    return _public_server(_find_server(data, server_id))


def update_server(
    agents_root: Path,
    agent_id: str,
    server_id: str,
    *,
    name: str | None = None,
    description: str | None = None,
    transport: str | None = None,
    enabled: bool | None = None,
    required: bool | None = None,
    timeout: float | None = None,
    url: str | None = None,
    command: str | None = None,
    args: list[str] | str | None = None,
    env: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    data, meta_file = _load_agent_json(agents_root, agent_id)
    servers = _get_servers(data)
    found_index, existing = _find_server_index(servers, server_id)

    final_transport = _normalise_transport(
        transport
        if transport is not None
        else str(existing.get("transport") or "")
    )
    updated = _build_server(
        server_id=server_id,
        name=name if name is not None else str(existing.get("name") or ""),
        description=(
            description
            if description is not None
            else str(existing.get("description") or "")
        ),
        transport=final_transport,
        enabled=(
            bool(enabled)
            if enabled is not None
            else bool(existing.get("enabled", True))
        ),
        required=(
            bool(required)
            if required is not None
            else bool(existing.get("required", False))
        ),
        timeout=(
            float(timeout)
            if timeout is not None
            else float(existing.get("timeout", 30.0) or 30.0)
        ),
        url=url if url is not None else _optional_str(existing.get("url")),
        command=(
            command
            if command is not None
            else _optional_str(existing.get("command"))
        ),
        args=args if args is not None else _string_list(existing.get("args")),
        env=env if env is not None else _string_map(existing.get("env")),
        headers=(
            headers
            if headers is not None
            else _string_map(existing.get("headers"))
        ),
    )
    tools = existing.get("tools")
    if isinstance(tools, dict):
        updated["tools"] = tools

    servers[found_index] = updated
    _write_agent_json(meta_file, data)
    return updated


def delete_server(
    agents_root: Path,
    agent_id: str,
    server_id: str,
) -> None:
    data, meta_file = _load_agent_json(agents_root, agent_id)
    servers = _get_servers(data)
    found_index, _ = _find_server_index(servers, server_id)
    del servers[found_index]
    _write_agent_json(meta_file, data)


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
    _, server = _find_server_index(_get_servers(data), server_id)
    return server


def _find_server_index(
    servers: list[Any],
    server_id: str,
) -> tuple[int, dict[str, Any]]:
    for index, server in enumerate(servers):
        if (
            isinstance(server, dict)
            and str(server.get("id") or "") == server_id
        ):
            return index, server
    raise KeyError(server_id)


def _build_server(
    *,
    server_id: str,
    name: str,
    description: str,
    transport: str,
    enabled: bool,
    required: bool,
    timeout: float,
    url: str | None = None,
    command: str | None = None,
    args: list[str] | str | None = None,
    env: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
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
        clean_headers = _string_map(headers)
        if clean_headers:
            server["headers"] = clean_headers
    else:
        command_parts = _split_shell_words((command or "").strip())
        if not command_parts:
            raise ValueError("MCP stdio server requires command")
        server["command"] = command_parts[0]
        server_args = [*command_parts[1:], *_normalise_args(args or [])]
        if server_args:
            server["args"] = server_args
        clean_env = _string_map(env)
        if clean_env:
            server["env"] = clean_env
    return server


def _public_server(server: Any) -> dict[str, Any]:
    if not isinstance(server, dict):
        return {}
    result = dict(server)
    result.setdefault("name", result.get("id") or "")
    result.setdefault("description", "")
    result.setdefault("transport", "")
    result.setdefault("enabled", True)
    result.setdefault("required", False)
    result.setdefault("timeout", 30.0)
    result.setdefault("args", [])
    result.setdefault("env", {})
    result.setdefault("headers", {})
    return result


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _string_map(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(k): str(v) for k, v in value.items()}


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


def _normalise_args(args: list[str] | str) -> list[str]:
    if isinstance(args, str):
        return _split_shell_words(args)
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
