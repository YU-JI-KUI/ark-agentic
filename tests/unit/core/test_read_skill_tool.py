"""Tests for read_skill tool."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from ark_agentic.core.skills.base import SkillConfig
from ark_agentic.core.skills.loader import SkillLoader
from ark_agentic.core.tools.read_skill import ReadSkillTool
from ark_agentic.core.types import ToolCall


def _create_skill_dir(tmpdir: str, skill_id: str, body: str, frontmatter: str = "") -> None:
    skill_dir = Path(tmpdir) / skill_id
    skill_dir.mkdir(parents=True)
    content = body
    if frontmatter:
        content = f"---\n{frontmatter}\n---\n\n{body}"
    (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")


@pytest.fixture
def read_skill_tool():
    """ReadSkillTool with one skill in temp dir."""
    with tempfile.TemporaryDirectory() as tmpdir:
        _create_skill_dir(
            tmpdir,
            "test_skill",
            "Full skill body content here.",
            "name: Test Skill\ndescription: A test\nwhen_to_use: When testing",
        )
        config = SkillConfig(skill_directories=[tmpdir])
        loader = SkillLoader(config)
        loader.load_from_directories()
        yield ReadSkillTool(loader)


@pytest.mark.asyncio
async def test_read_skill_valid_id_returns_digest(read_skill_tool: ReadSkillTool) -> None:
    """Skill 一等公民：valid skill_id 只返回加载凭证 digest（含 name/id、不含正文），
    同时通过 typed `session_effects` 触发 SSOT 写入；正文由下一轮 system prompt 注入。
    """
    tc = ToolCall.create("read_skill", {"skill_id": "test_skill"})
    result = await read_skill_tool.execute(tc, context=None)
    assert not result.is_error
    text = result.content if isinstance(result.content, str) else str(result.content)
    # digest 应包含 skill 身份标识
    assert "Test Skill" in text
    assert "test_skill" in text
    # digest 应明确指示"下一轮 system prompt 有正文"，且不重复正文
    assert "active" in text.lower()
    assert "Full skill body content here." not in text
    # 通过 typed session_effects 通道触发 SSOT 写入（不经由 state_delta）
    assert result.metadata.get("session_effects") == [
        {"op": "activate_skill", "skill_ids": ["test_skill"]}
    ]
    assert "state_delta" not in result.metadata


@pytest.mark.asyncio
async def test_read_skill_unknown_id_returns_error(read_skill_tool: ReadSkillTool) -> None:
    """Unknown skill_id returns clear error message."""
    tc = ToolCall.create("read_skill", {"skill_id": "nonexistent_skill"})
    result = await read_skill_tool.execute(tc, context=None)
    assert "unknown skill id" in result.content.lower() or "error" in result.content.lower()
    assert "nonexistent_skill" in result.content


@pytest.mark.asyncio
async def test_read_skill_empty_id_returns_error(read_skill_tool: ReadSkillTool) -> None:
    """Empty skill_id returns error."""
    tc = ToolCall.create("read_skill", {"skill_id": ""})
    result = await read_skill_tool.execute(tc, context=None)
    assert "skill_id" in result.content.lower() or "error" in result.content.lower()
