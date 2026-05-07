"""Tests for MetaBuilder 方案 A：3 个复合工具注册与基本行为。"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from unittest.mock import patch

from ark_agentic.agents.meta_builder import MetaBuilderAgent
from ark_agentic.agents.meta_builder.tools.manage_agents import ManageAgentsTool
from ark_agentic.agents.meta_builder.tools.manage_skills import ManageSkillsTool
from ark_agentic.agents.meta_builder.tools.manage_tools import ManageToolsTool
from ark_agentic.core.types import ToolCall


class _MockLLM:
    async def chat(self, messages, tools=None, stream=False, **kwargs):
        return None


def test_meta_builder_registers_three_composite_tools(tmp_path, monkeypatch):
    """MetaBuilderAgent registers manage_agents / manage_skills / manage_tools.

    Full skill_load_mode means no auto-registered read_skill tool.
    """
    monkeypatch.setenv("SESSIONS_DIR", str(tmp_path))
    with patch.object(MetaBuilderAgent, "build_llm", return_value=_MockLLM()):
        agent = MetaBuilderAgent()
    tools = agent.tool_registry.list_all()
    names = {t.name for t in tools}
    assert {"manage_agents", "manage_skills", "manage_tools"}.issubset(names)
    assert len(tools) >= 3


def test_manage_agents_schema_has_action_enum():
    """manage_agents 的 action 参数为 enum list/create/delete。"""
    t = ManageAgentsTool()
    schema = t.get_json_schema()
    params = schema["function"]["parameters"]["properties"]
    assert "action" in params
    assert params["action"].get("enum") == ["list", "create", "delete"]
    assert "action" in schema["function"]["parameters"]["required"]


def test_manage_skills_schema_has_action_enum():
    """manage_skills 的 action 为 list/create/update/delete/read。"""
    t = ManageSkillsTool()
    schema = t.get_json_schema()
    params = schema["function"]["parameters"]["properties"]
    assert params["action"].get("enum") == ["list", "create", "update", "delete", "read"]


def test_manage_tools_schema_has_action_enum():
    """manage_tools 的 action 为 list/create/update/delete/read。"""
    t = ManageToolsTool()
    schema = t.get_json_schema()
    params = schema["function"]["parameters"]["properties"]
    assert params["action"].get("enum") == ["list", "create", "update", "delete", "read"]


def _text(r: object) -> str:
    """AgentToolResult 的文本内容。"""
    return str(r.content) if hasattr(r, "content") else str(r)


@pytest.mark.asyncio
async def test_manage_agents_list_empty_agents_root(monkeypatch, tmp_path):
    """manage_agents action=list 在空 agents 根目录下返回“当前没有任何 Agent”。"""
    monkeypatch.setenv("AGENTS_ROOT", str(tmp_path))
    tool = ManageAgentsTool()
    result = await tool.execute(
        ToolCall(id="tc1", name="manage_agents", arguments={"action": "list"}),
        context=None,
    )
    text = _text(result)
    assert "当前没有任何 Agent" in text or "0 个 Agent" in text


@pytest.mark.asyncio
async def test_manage_agents_invalid_action_returns_error():
    """manage_agents action 非法时返回错误信息。"""
    tool = ManageAgentsTool()
    result = await tool.execute(
        ToolCall(id="tc1", name="manage_agents", arguments={"action": "invalid"}),
        context=None,
    )
    assert result.is_error
    assert "action" in _text(result).lower()


@pytest.mark.asyncio
async def test_manage_skills_create_without_name_returns_error():
    """manage_skills action=create 且未提供 name 时返回明确错误。"""
    tool = ManageSkillsTool()
    result = await tool.execute(
        ToolCall(
            id="tc1",
            name="manage_skills",
            arguments={"action": "create", "agent_id": "some-agent"},
        ),
        context=None,
    )
    assert result.is_error
    assert "name" in _text(result).lower()


@pytest.mark.asyncio
async def test_manage_tools_tool_name_not_identifier_returns_error():
    """manage_tools update/delete/read 时 tool_name 非标识符返回错误。"""
    tool = ManageToolsTool()
    result = await tool.execute(
        ToolCall(
            id="tc1",
            name="manage_tools",
            arguments={
                "action": "read",
                "agent_id": "meta_builder",
                "tool_name": "bad-name-with-dash",
            },
        ),
        context=None,
    )
    assert result.is_error
    text = _text(result)
    assert "标识符" in text or "identifier" in text.lower()


@pytest.mark.asyncio
async def test_manage_agents_create_without_confirmation_returns_error(monkeypatch, tmp_path):
    """manage_agents action=create 未传 confirmation 时要求用户确认。"""
    monkeypatch.setenv("AGENTS_ROOT", str(tmp_path))
    tool = ManageAgentsTool()
    result = await tool.execute(
        ToolCall(
            id="tc1",
            name="manage_agents",
            arguments={"action": "create", "name": "TestAgent"},
        ),
        context=None,
    )
    assert result.is_error
    text = _text(result)
    assert "我确认变更" in text


@pytest.mark.asyncio
async def test_manage_agents_delete_meta_builder_forbidden(monkeypatch, tmp_path):
    """禁止删除 meta_builder 自身。"""
    monkeypatch.setenv("AGENTS_ROOT", str(tmp_path))
    tool = ManageAgentsTool()
    result = await tool.execute(
        ToolCall(
            id="tc1",
            name="manage_agents",
            arguments={
                "action": "delete",
                "agent_id": "meta_builder",
                "confirmation": "我确认变更",
            },
        ),
        context=None,
    )
    assert result.is_error
    text = _text(result)
    assert "不能删除" in text or "Meta-Agent" in text
