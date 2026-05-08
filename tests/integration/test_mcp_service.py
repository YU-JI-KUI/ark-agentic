from __future__ import annotations

import json
from pathlib import Path

import pytest

from ark_agentic.plugins.studio.services.mcp_service import (
    create_server,
    delete_server,
    get_server,
    list_servers,
    update_server,
)


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


def _mcp_config_file(agents_root: Path) -> Path:
    return agents_root / "config" / "test_agent" / "mcp.json"


def _read_mcp_config(agents_root: Path) -> dict:
    content = _mcp_config_file(agents_root).read_text(encoding="utf-8")
    return json.loads(content)


def test_create_http_mcp_server_updates_mcp_json(agents_root: Path) -> None:
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

    data = _read_mcp_config(agents_root)

    [server] = data["servers"]
    assert created["id"] == "crm"
    assert server["name"] == "CRM"
    assert server["transport"] == "streamable_http"
    assert server["url"] == "http://127.0.0.1:9000/mcp"
    assert server["headers"]["Authorization"] == "Bearer ${CRM_TOKEN}"
    assert server["enabled"] is True
    agent_data = json.loads(
        (agents_root / "test_agent" / "agent.json").read_text(
            encoding="utf-8",
        )
    )
    assert "mcp" not in agent_data


def test_list_mcp_servers_without_mcp_json_is_empty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path / "config"))
    (tmp_path / "empty_agent").mkdir()

    assert list_servers(tmp_path, "empty_agent") == []


def test_create_stdio_mcp_server_updates_mcp_json(agents_root: Path) -> None:
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

    data = _read_mcp_config(agents_root)

    [server] = data["servers"]
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

    data = _read_mcp_config(agents_root)

    [server] = data["servers"]
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


def test_update_http_mcp_server_preserves_tool_policy(
    agents_root: Path,
) -> None:
    create_server(
        agents_root,
        "test_agent",
        "crm",
        transport="streamable_http",
        url="http://127.0.0.1:9000/mcp",
    )
    data_file = _mcp_config_file(agents_root)
    data = json.loads(data_file.read_text(encoding="utf-8"))
    data["servers"][0]["tools"] = {"enabled": {"lookup": False}}
    data_file.write_text(json.dumps(data), encoding="utf-8")

    updated = update_server(
        agents_root,
        "test_agent",
        "crm",
        name="CRM MCP",
        description="Updated customer tools",
        transport="http",
        url="http://127.0.0.1:9001/mcp",
        headers={"Authorization": "Bearer ${CRM_TOKEN}"},
        enabled=False,
        required=True,
        timeout=45,
    )

    stored = get_server(agents_root, "test_agent", "crm")
    assert updated["name"] == "CRM MCP"
    assert stored["description"] == "Updated customer tools"
    assert stored["transport"] == "streamable_http"
    assert stored["url"] == "http://127.0.0.1:9001/mcp"
    assert stored["headers"] == {"Authorization": "Bearer ${CRM_TOKEN}"}
    assert stored["enabled"] is False
    assert stored["required"] is True
    assert stored["timeout"] == 45
    assert stored["tools"] == {"enabled": {"lookup": False}}


def test_update_mcp_server_can_switch_to_stdio(
    agents_root: Path,
) -> None:
    create_server(
        agents_root,
        "test_agent",
        "math",
        transport="streamable_http",
        url="http://127.0.0.1:9000/mcp",
    )

    update_server(
        agents_root,
        "test_agent",
        "math",
        transport="stdio",
        command="uv run --with mcp",
        args=["tests/mcp/math-server.py"],
        env={"PYTHONUNBUFFERED": "1"},
    )

    stored = get_server(agents_root, "test_agent", "math")
    assert stored["transport"] == "stdio"
    assert stored["command"] == "uv"
    assert stored["args"] == [
        "run",
        "--with",
        "mcp",
        "tests/mcp/math-server.py",
    ]
    assert stored["env"] == {"PYTHONUNBUFFERED": "1"}
    assert "url" not in stored


def test_delete_mcp_server_removes_config(
    agents_root: Path,
) -> None:
    create_server(
        agents_root,
        "test_agent",
        "crm",
        transport="streamable_http",
        url="http://127.0.0.1:9000/mcp",
    )

    delete_server(agents_root, "test_agent", "crm")

    data = _read_mcp_config(agents_root)
    assert data["servers"] == []
    with pytest.raises(KeyError):
        get_server(agents_root, "test_agent", "crm")


def test_create_stdio_mcp_server_with_string_args(agents_root: Path) -> None:
    create_server(
        agents_root,
        "test_agent",
        "str_args",
        transport="stdio",
        command="uv",
        args="run --with mcp server.py",
    )

    stored = get_server(agents_root, "test_agent", "str_args")
    assert stored["command"] == "uv"
    assert stored["args"] == ["run", "--with", "mcp", "server.py"]
