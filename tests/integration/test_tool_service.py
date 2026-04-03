"""
Tool Service tests — 直接测试 Service 层，不依赖 FastAPI。
"""

import ast
import pytest
from pathlib import Path

from ark_agentic.studio.services.tool_service import (
    scaffold_tool,
    list_tools,
    parse_tool_file,
    render_tool_template,
    _to_class_name,
)


@pytest.fixture
def agents_root(tmp_path: Path) -> Path:
    """创建临时 Agent 目录结构。"""
    tools_dir = tmp_path / "test_agent" / "tools"
    tools_dir.mkdir(parents=True)
    # 创建 __init__.py
    (tools_dir / "__init__.py").write_text("", encoding="utf-8")
    return tmp_path


@pytest.fixture
def seeded_root(agents_root: Path) -> Path:
    """预置一个 AgentTool 文件。"""
    tool_code = '''
from ark_agentic.core.tools.base import AgentTool, ToolParameter
from ark_agentic.core.types import AgentToolResult, ToolCall

class MyExistingTool(AgentTool):
    """An existing tool"""
    name = "my_existing"
    description = "Existing tool"
    parameters = []

    async def execute(self, tool_call: ToolCall) -> AgentToolResult:
        return AgentToolResult(output="ok")
'''
    (agents_root / "test_agent" / "tools" / "my_existing.py").write_text(
        tool_code, encoding="utf-8"
    )
    return agents_root


# ── Class Name ──────────────────────────────────────────────────────

def test_to_class_name():
    assert _to_class_name("my_tool") == "MyTool"  # 'Tool' already in parts
    assert _to_class_name("customer_info") == "CustomerInfoTool"
    assert _to_class_name("query") == "QueryTool"


# ── Scaffold ────────────────────────────────────────────────────────

def test_scaffold_tool(agents_root):
    meta = scaffold_tool(
        agents_root, "test_agent",
        name="new_tool",
        description="A new tool",
        parameters=[{"name": "query", "description": "Search query", "type": "string", "required": True}],
    )
    assert meta.name == "new_tool"

    # 文件系统验证
    tool_file = agents_root / "test_agent" / "tools" / "new_tool.py"
    assert tool_file.is_file()

    # AST 验证：生成的代码可以解析
    source = tool_file.read_text(encoding="utf-8")
    tree = ast.parse(source)
    class_names = [n.id for n in ast.walk(tree) if isinstance(n, ast.Name)]
    assert "NewTool" in [n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
    assert "AgentTool" in class_names


def test_scaffold_tool_duplicate_raises(seeded_root):
    with pytest.raises(FileExistsError):
        scaffold_tool(seeded_root, "test_agent", name="my_existing")


def test_scaffold_tool_invalid_name_raises(agents_root):
    with pytest.raises(ValueError):
        scaffold_tool(agents_root, "test_agent", name="invalid-name")


def test_scaffold_tool_agent_not_found(agents_root):
    with pytest.raises(FileNotFoundError):
        scaffold_tool(agents_root, "nonexistent", name="test")


# ── Parse ───────────────────────────────────────────────────────────

def test_parse_tool_file(seeded_root):
    tool_file = seeded_root / "test_agent" / "tools" / "my_existing.py"
    meta = parse_tool_file(tool_file, "test_agent")
    assert meta is not None
    assert meta.name == "my_existing"
    assert meta.description == "Existing tool"  # class attribute overrides docstring


def test_parse_non_tool_returns_none(agents_root):
    helper = agents_root / "test_agent" / "tools" / "helper.py"
    helper.write_text("class NotATool:\n    pass\n", encoding="utf-8")
    assert parse_tool_file(helper, "test_agent") is None


# ── List ────────────────────────────────────────────────────────────

def test_list_tools_empty(agents_root):
    tools = list_tools(agents_root, "test_agent")
    assert tools == []


def test_list_tools_with_data(seeded_root):
    tools = list_tools(seeded_root, "test_agent")
    assert len(tools) == 1
    assert tools[0].name == "my_existing"


def test_list_tools_discovers_nested_agent_tool(agents_root: Path):
    """rglob: tools under subdirs (e.g. tools/agent/) are listed with correct file_path."""
    sub = agents_root / "test_agent" / "tools" / "agent"
    sub.mkdir(parents=True)
    code = '''
from ark_agentic.core.tools.base import AgentTool
from ark_agentic.core.types import AgentToolResult, ToolCall

class NestedTool(AgentTool):
    """nested"""
    name = "nested_tool"
    description = "from subdir"
    parameters = []

    async def execute(self, tool_call: ToolCall) -> AgentToolResult:
        return AgentToolResult(output="ok")
'''
    (sub / "nested_tool.py").write_text(code, encoding="utf-8")

    tools = list_tools(agents_root, "test_agent")
    names = {t.name for t in tools}
    assert "nested_tool" in names
    nested = next(t for t in tools if t.name == "nested_tool")
    assert nested.file_path.replace("\\", "/") == "tools/agent/nested_tool.py"


def test_parse_tool_file_file_path_relative_to_agent_dir(seeded_root: Path):
    tool_file = seeded_root / "test_agent" / "tools" / "my_existing.py"
    agent_dir = seeded_root / "test_agent"
    meta = parse_tool_file(tool_file, "test_agent", agent_dir)
    assert meta is not None
    assert meta.file_path.replace("\\", "/") == "tools/my_existing.py"


# ── Template Render ─────────────────────────────────────────────────

def test_render_tool_template():
    code = render_tool_template("my_tool", "A tool")
    assert "class MyTool(AgentTool)" in code
    assert 'name = "my_tool"' in code
    assert "async def execute" in code
    # 验证可解析
    ast.parse(code)
