"""Configuration helpers for MCP client integrations."""

from __future__ import annotations

import json
import os
import re
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from ark_agentic.core.paths import resolve_agent_config_file


MCPTransport = Literal["stdio", "streamable_http"]

_ENV_REF_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
_SERVER_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


@dataclass(frozen=True)
class MCPToolPolicy:
    """Per-server tool exposure policy."""

    allow: list[str] = field(default_factory=lambda: ["*"])
    deny: list[str] = field(default_factory=list)
    enabled: dict[str, bool] = field(default_factory=dict)

    def is_allowed(self, tool_name: str) -> bool:
        allowed = "*" in self.allow or tool_name in self.allow
        return allowed and tool_name not in self.deny

    def is_enabled(self, tool_name: str) -> bool:
        return self.enabled.get(tool_name, True)


@dataclass(frozen=True)
class MCPServerConfig:
    """MCP server declaration loaded from an agent's ``agent.json``."""

    id: str
    name: str
    description: str
    transport: MCPTransport
    enabled: bool = True
    required: bool = False
    timeout: float = 30.0
    url: str | None = None
    command: str | None = None
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    tools: MCPToolPolicy = field(default_factory=MCPToolPolicy)


def load_agent_mcp_config(agent_dir: Path) -> list[MCPServerConfig]:
    """Read and validate MCP server config from ``agent.json``.

    Missing ``agent.json`` or missing ``mcp.servers`` means no MCP servers.
    """
    meta_file = agent_dir / "agent.json"
    if not meta_file.is_file():
        return []
    data = json.loads(meta_file.read_text(encoding="utf-8"))
    mcp_raw = data.get("mcp") or {}
    if not isinstance(mcp_raw, dict):
        raise ValueError("agent.json mcp must be an object")
    raw_servers = mcp_raw.get("servers") or []
    if not isinstance(raw_servers, list):
        raise ValueError("agent.json mcp.servers must be a list")
    return [_parse_server(raw) for raw in raw_servers if isinstance(raw, dict)]


def load_agent_mcp_config_for_agent(
    agent_id: str,
    legacy_agent_dir: Path | None = None,
) -> list[MCPServerConfig]:
    """Read MCP config from CONFIG_DIR, falling back to legacy location."""
    meta_file = resolve_agent_config_file(
        agent_id,
        legacy_agent_dir=legacy_agent_dir,
    )
    if meta_file is None:
        return []
    data = json.loads(meta_file.read_text(encoding="utf-8"))
    mcp_raw = data.get("mcp") or {}
    if not isinstance(mcp_raw, dict):
        raise ValueError("agent.json mcp must be an object")
    raw_servers = mcp_raw.get("servers") or []
    if not isinstance(raw_servers, list):
        raise ValueError("agent.json mcp.servers must be a list")
    return [_parse_server(raw) for raw in raw_servers if isinstance(raw, dict)]


def expand_env_refs(value: Any) -> Any:
    """Expand ``${VAR}`` references inside strings, lists and dictionaries."""
    if isinstance(value, str):
        def repl(match: re.Match[str]) -> str:
            env_name = match.group(1)
            if env_name not in os.environ:
                raise ValueError(f"Environment variable not set: {env_name}")
            return os.environ[env_name]

        return _ENV_REF_RE.sub(repl, value)
    if isinstance(value, list):
        return [expand_env_refs(item) for item in value]
    if isinstance(value, dict):
        return {str(k): expand_env_refs(v) for k, v in value.items()}
    return value


def mcp_registered_tool_name(server_id: str, remote_tool_name: str) -> str:
    return f"mcp__{server_id}__{remote_tool_name}"


def _parse_server(raw: dict[str, Any]) -> MCPServerConfig:
    server_id = str(raw.get("id") or "").strip()
    if not server_id or not _SERVER_ID_RE.match(server_id):
        raise ValueError(f"Invalid MCP server id: {server_id!r}")

    transport_raw = (
        str(raw.get("transport") or "")
        .strip()
        .lower()
        .replace("-", "_")
    )
    if transport_raw in {"http", "streamable"}:
        transport_raw = "streamable_http"
    if transport_raw not in {"stdio", "streamable_http"}:
        raise ValueError(
            f"Unsupported MCP transport for {server_id}: {transport_raw}"
        )

    timeout = float(raw.get("timeout", 30.0) or 30.0)
    tools_raw = raw.get("tools") or {}
    if not isinstance(tools_raw, dict):
        tools_raw = {}
    allow_raw = tools_raw.get("allow", ["*"])
    if not isinstance(allow_raw, list):
        allow_raw = [allow_raw]
    deny_raw = tools_raw.get("deny", [])
    if not isinstance(deny_raw, list):
        deny_raw = [deny_raw]
    enabled_raw = tools_raw.get("enabled") or {}
    if not isinstance(enabled_raw, dict):
        enabled_raw = {}

    policy = MCPToolPolicy(
        allow=[str(x) for x in allow_raw],
        deny=[str(x) for x in deny_raw],
        enabled={
            str(k): bool(v)
            for k, v in enabled_raw.items()
        },
    )

    expanded_env = expand_env_refs(raw.get("env") or {})
    expanded_headers = expand_env_refs(raw.get("headers") or {})
    expanded_args = expand_env_refs(raw.get("args") or [])
    expanded_url = expand_env_refs(raw.get("url")) if raw.get("url") else None
    expanded_command = (
        expand_env_refs(raw.get("command")) if raw.get("command") else None
    )
    expanded_command, expanded_args = _normalise_command_args(
        expanded_command,
        expanded_args,
    )

    if transport_raw == "stdio" and not expanded_command:
        raise ValueError(f"MCP stdio server {server_id} requires command")
    if transport_raw == "streamable_http" and not expanded_url:
        raise ValueError(f"MCP HTTP server {server_id} requires url")

    return MCPServerConfig(
        id=server_id,
        name=str(raw.get("name") or server_id),
        description=str(raw.get("description") or ""),
        transport=transport_raw,  # type: ignore[arg-type]
        enabled=bool(raw.get("enabled", True)),
        required=bool(raw.get("required", False)),
        timeout=timeout,
        url=expanded_url,
        command=expanded_command,
        args=expanded_args,
        env={str(k): str(v) for k, v in expanded_env.items()},
        headers={str(k): str(v) for k, v in expanded_headers.items()},
        tools=policy,
    )


def _normalise_command_args(
    command: Any,
    args: Any,
) -> tuple[str | None, list[str]]:
    split_command = _split_shell_words(str(command)) if command else []
    if not isinstance(args, list):
        args = [args]
    split_args: list[str] = []
    for arg in args:
        split_args.extend(_split_shell_words(str(arg)))
    if not split_command:
        return None, split_args
    return split_command[0], [*split_command[1:], *split_args]


def _split_shell_words(value: str) -> list[str]:
    try:
        return shlex.split(value)
    except ValueError as exc:
        raise ValueError(f"Invalid shell command fragment: {value}") from exc
