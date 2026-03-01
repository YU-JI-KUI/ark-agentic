"""
Studio Tools API integration tests — uses TestClient against HTTP endpoints.
Updated for Phase 4 Service layer refactoring.
"""

import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from fastapi import FastAPI

from ark_agentic.studio.api.tools import router as tools_router
from ark_agentic.studio.services.tool_service import parse_tool_file

app = FastAPI()
app.include_router(tools_router)
client = TestClient(app)


@pytest.fixture
def mock_agents_root(tmp_path, monkeypatch):
    """Mock the _agents_root function to return a temp directory."""
    def mock_root():
        return tmp_path
    monkeypatch.setattr("ark_agentic.studio.api.tools._agents_root", mock_root)
    return tmp_path


def test_parse_tool_file_success(tmp_path):
    tool_file = tmp_path / "my_tool.py"
    tool_file.write_text('''
from ark_agentic.core.tools.base import AgentTool

class MyTool(AgentTool):
    """Reads a file."""
    name = "test_tool"
    description = "Test description"
    group = "test_group"
''', encoding="utf-8")

    meta = parse_tool_file(tool_file, "test_agent")
    assert meta is not None
    assert meta.name == "test_tool"
    assert meta.description == "Test description"
    assert meta.group == "test_group"
    assert meta.file_path == "agents/test_agent/tools/my_tool.py"


def test_parse_tool_file_no_agent_tool(tmp_path):
    """Classes not inheriting AgentTool should return None."""
    tool_file = tmp_path / "empty_tool.py"
    tool_file.write_text('class EmptyTool:\n    pass\n', encoding="utf-8")

    meta = parse_tool_file(tool_file, "test_agent")
    assert meta is None  # not an AgentTool subclass


def test_parse_tool_file_invalid_syntax(tmp_path):
    tool_file = tmp_path / "bad.py"
    tool_file.write_text('class 1: pass', encoding="utf-8")
    assert parse_tool_file(tool_file, "test_agent") is None


def test_list_tools_success(mock_agents_root):
    agent_dir = mock_agents_root / "agent1"
    agent_dir.mkdir()
    tools_dir = agent_dir / "tools"
    tools_dir.mkdir()

    (tools_dir / "tool_a.py").write_text('''
from ark_agentic.core.tools.base import AgentTool

class ToolA(AgentTool):
    name = "a"
''', encoding="utf-8")
    (tools_dir / "_tool.py").write_text('class B:\n    name="b"', encoding="utf-8")

    response = client.get("/agents/agent1/tools")
    assert response.status_code == 200
    data = response.json()
    assert len(data["tools"]) == 1
    assert data["tools"][0]["name"] == "a"


def test_list_tools_agent_not_found(mock_agents_root):
    response = client.get("/agents/missing/tools")
    assert response.status_code == 404
