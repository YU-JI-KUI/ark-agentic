from __future__ import annotations

import json
from pathlib import Path

import pytest

from ark_agentic.plugins.studio.services.mcp_service import create_server


@pytest.fixture
def agents_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path / "config"))
    agent_dir = tmp_path / "test_agent"
    agent_dir.mkdir()
    (agent_dir / "agent.json").write_text(
        json.dumps({"id": "test_agent"}),
        encoding="utf-8",
    )
    return tmp_path


def test_create_http_mcp_server_updates_agent_json(agents_root: Path) -> None:
    created = create_server(
        agents_root,
        "test_agent",
        "crm",
        name="CRM",
        description="Customer tools",
        transport="http",
        url="http://127.0.0.1:9000/mcp",
        headers={"Authorization": "Bearer ${CRM_TOKEN}"},
    )

    data = json.loads(
        (agents_root / "config" / "test_agent" / "agent.json").read_text(
            encoding="utf-8",
        )
    )

    [server] = data["mcp"]["servers"]
    assert created["id"] == "crm"
    assert server["name"] == "CRM"
    assert server["transport"] == "streamable_http"
    assert server["url"] == "http://127.0.0.1:9000/mcp"
    assert server["headers"]["Authorization"] == "Bearer ${CRM_TOKEN}"
    assert server["enabled"] is True


def test_create_stdio_mcp_server_updates_agent_json(agents_root: Path) -> None:
    create_server(
        agents_root,
        "test_agent",
        "local",
        transport="stdio",
        command="uvx",
        args=["mcp-server --project ."],
        env={"API_TOKEN": "${API_TOKEN}"},
        enabled=False,
    )

    data = json.loads(
        (agents_root / "config" / "test_agent" / "agent.json").read_text(
            encoding="utf-8",
        )
    )

    [server] = data["mcp"]["servers"]
    assert server["command"] == "uvx"
    assert server["args"] == ["mcp-server", "--project", "."]
    assert server["env"]["API_TOKEN"] == "${API_TOKEN}"
    assert server["enabled"] is False


def test_create_stdio_mcp_server_splits_full_command(
    agents_root: Path,
) -> None:
    create_server(
        agents_root,
        "test_agent",
        "math",
        transport="stdio",
        command="uv run --with mcp",
        args=["tests/mcp/math-server.py"],
    )

    data = json.loads(
        (agents_root / "config" / "test_agent" / "agent.json").read_text(
            encoding="utf-8",
        )
    )

    [server] = data["mcp"]["servers"]
    assert server["command"] == "uv"
    assert server["args"] == [
        "run",
        "--with",
        "mcp",
        "tests/mcp/math-server.py",
    ]


def test_create_mcp_server_duplicate_raises(agents_root: Path) -> None:
    create_server(
        agents_root,
        "test_agent",
        "crm",
        transport="streamable_http",
        url="http://127.0.0.1:9000/mcp",
    )

    with pytest.raises(FileExistsError):
        create_server(
            agents_root,
            "test_agent",
            "crm",
            transport="streamable_http",
            url="http://127.0.0.1:9001/mcp",
        )


def test_create_mcp_server_requires_transport_target(
    agents_root: Path,
) -> None:
    with pytest.raises(ValueError, match="requires url"):
        create_server(
            agents_root,
            "test_agent",
            "http_missing_url",
            transport="streamable_http",
        )

    with pytest.raises(ValueError, match="requires command"):
        create_server(
            agents_root,
            "test_agent",
            "stdio_missing_command",
            transport="stdio",
        )
