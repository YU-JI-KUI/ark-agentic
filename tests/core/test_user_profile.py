"""Tests for user profile (USER.md) management and injection."""

import tempfile
from pathlib import Path

import pytest

from ark_agentic.core.memory.user_profile import (
    _DEFAULT_TEMPLATE,
    _PROFILES_DIR,
    append_to_profile,
    ensure_user_profile,
    get_profile_path,
    load_user_profile,
    truncate_profile,
)
from ark_agentic.core.paths import get_memory_base_dir
from ark_agentic.core.prompt.builder import SystemPromptBuilder
from ark_agentic.core.tools.memory import ProfileSetTool, create_memory_tools
from ark_agentic.core.types import ToolCall


# ============ user_profile.py functions ============


class TestGetProfilePath:
    def test_returns_correct_path(self) -> None:
        base = Path("/data/ark_memory")
        path = get_profile_path(base, "user_123")
        assert path == base / _PROFILES_DIR / "user_123" / "USER.md"

    def test_profiles_dir_isolation(self) -> None:
        """_profiles/ prefix prevents collision with agent directories."""
        base = Path("/data/ark_memory")
        profile = get_profile_path(base, "alice")
        agent_dir = base / "insurance" / "alice"
        assert _PROFILES_DIR in str(profile)
        assert str(profile).startswith(str(base / _PROFILES_DIR))
        assert not str(profile).startswith(str(agent_dir))


class TestLoadUserProfile:
    def test_returns_empty_when_not_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            content = load_user_profile(Path(tmpdir), "nonexistent_user")
            assert content == ""

    def test_reads_existing_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            profile_dir = base / _PROFILES_DIR / "user1"
            profile_dir.mkdir(parents=True)
            (profile_dir / "USER.md").write_text("# My Profile\n- likes python", encoding="utf-8")

            content = load_user_profile(base, "user1")
            assert "My Profile" in content
            assert "likes python" in content


class TestEnsureUserProfile:
    def test_creates_template_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            path = ensure_user_profile(base, "new_user")
            assert path.exists()
            content = path.read_text(encoding="utf-8")
            assert content == _DEFAULT_TEMPLATE

    def test_does_not_overwrite_existing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            profile_dir = base / _PROFILES_DIR / "user1"
            profile_dir.mkdir(parents=True)
            existing = "# Custom profile"
            (profile_dir / "USER.md").write_text(existing, encoding="utf-8")

            path = ensure_user_profile(base, "user1")
            assert path.read_text(encoding="utf-8") == existing


class TestAppendToProfile:
    def test_append_creates_file_if_needed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            written = append_to_profile(base, "user1", "- prefers Chinese")
            assert written > 0
            content = load_user_profile(base, "user1")
            assert "prefers Chinese" in content

    def test_append_with_section(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            append_to_profile(base, "user1", "concise replies", section="## 沟通风格")
            content = load_user_profile(base, "user1")
            assert "## 沟通风格" in content
            assert "concise replies" in content

    def test_append_preserves_existing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            ensure_user_profile(base, "user1")
            append_to_profile(base, "user1", "- item A")
            append_to_profile(base, "user1", "- item B")
            content = load_user_profile(base, "user1")
            assert "item A" in content
            assert "item B" in content
            assert "用户画像" in content  # template header preserved


class TestTruncateProfile:
    def test_short_content_unchanged(self) -> None:
        content = "- likes python\n- timezone: UTC"
        assert truncate_profile(content, max_tokens=1000) == content

    def test_empty_content(self) -> None:
        assert truncate_profile("", max_tokens=100) == ""

    def test_long_content_truncated(self) -> None:
        long_content = "测试内容 " * 2000
        result = truncate_profile(long_content, max_tokens=100)
        assert len(result) < len(long_content)
        assert result.endswith("... (truncated)")


# ============ paths.py ============


class TestGetMemoryBaseDir:
    def test_default_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MEMORY_DIR", raising=False)
        assert get_memory_base_dir() == Path("data/ark_memory")

    def test_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MEMORY_DIR", "/custom/memory")
        assert get_memory_base_dir() == Path("/custom/memory")


# ============ SystemPromptBuilder.add_user_profile ============


class TestBuilderUserProfile:
    def test_add_user_profile(self) -> None:
        builder = SystemPromptBuilder()
        builder.add_user_profile("- 偏好中文回复\n- 技术水平：专家")
        prompt = builder.build()
        assert "用户画像" in prompt
        assert "偏好中文回复" in prompt
        assert "技术水平：专家" in prompt

    def test_add_user_profile_empty(self) -> None:
        builder = SystemPromptBuilder()
        builder.add_user_profile("")
        assert len(builder._sections) == 0

    def test_quick_build_with_profile(self) -> None:
        prompt = SystemPromptBuilder.quick_build(
            user_profile_content="- timezone: Asia/Shanghai"
        )
        assert "用户画像" in prompt
        assert "timezone: Asia/Shanghai" in prompt

    def test_quick_build_without_profile(self) -> None:
        prompt = SystemPromptBuilder.quick_build()
        assert "用户画像" not in prompt

    def test_profile_section_order(self) -> None:
        """user_profile appears after runtime but before tools."""
        builder = SystemPromptBuilder()
        builder.add_identity(name="Bot")
        builder.add_runtime_info()
        builder.add_user_profile("profile content")
        builder.add_tools([])
        builder.add_memory_instructions()
        prompt = builder.build()

        sections = [name for name, _ in builder._sections]
        profile_idx = sections.index("user_profile")
        identity_idx = sections.index("identity")
        assert profile_idx > identity_idx

        runtime_idx = sections.index("runtime")
        assert profile_idx > runtime_idx


# ============ ProfileSetTool ============


class TestProfileSetTool:
    def test_metadata(self) -> None:
        tool = ProfileSetTool()
        assert tool.name == "profile_set"
        assert "USER.md" in tool.description
        assert len(tool.parameters) == 2

    @pytest.mark.asyncio
    async def test_write_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            import os
            os.environ["MEMORY_DIR"] = tmpdir
            try:
                tool = ProfileSetTool()
                call = ToolCall(
                    id="call_1",
                    name="profile_set",
                    arguments={"content": "- prefers dark mode"},
                )
                result = await tool.execute(call, {"user:id": "test_user"})
                assert result.content["status"] == "written"
                assert result.content["bytes_written"] > 0

                content = load_user_profile(Path(tmpdir), "test_user")
                assert "prefers dark mode" in content
            finally:
                del os.environ["MEMORY_DIR"]

    @pytest.mark.asyncio
    async def test_write_with_section(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            import os
            os.environ["MEMORY_DIR"] = tmpdir
            try:
                tool = ProfileSetTool()
                call = ToolCall(
                    id="call_1",
                    name="profile_set",
                    arguments={"content": "简洁直接", "section": "## 沟通风格"},
                )
                result = await tool.execute(call, {"user:id": "test_user"})
                assert result.content["status"] == "written"

                content = load_user_profile(Path(tmpdir), "test_user")
                assert "## 沟通风格" in content
                assert "简洁直接" in content
            finally:
                del os.environ["MEMORY_DIR"]

    @pytest.mark.asyncio
    async def test_missing_content(self) -> None:
        tool = ProfileSetTool()
        call = ToolCall(id="call_1", name="profile_set", arguments={"content": ""})
        result = await tool.execute(call, {"user:id": "test_user"})
        assert result.result_type.value == "error"

    @pytest.mark.asyncio
    async def test_missing_user_id(self) -> None:
        tool = ProfileSetTool()
        call = ToolCall(
            id="call_1",
            name="profile_set",
            arguments={"content": "something"},
        )
        result = await tool.execute(call, {})
        assert result.result_type.value == "error"

    def test_included_in_create_memory_tools(self) -> None:
        from unittest.mock import MagicMock
        provider = lambda uid: MagicMock()
        tools = create_memory_tools(provider)
        names = [t.name for t in tools]
        assert "profile_set" in names


# ============ MEMORY_INSTRUCTIONS ============


class TestMemoryInstructions:
    def test_instructions_mention_profile_set(self) -> None:
        from ark_agentic.core.prompt.builder import MEMORY_INSTRUCTIONS
        assert "profile_set" in MEMORY_INSTRUCTIONS
        assert "memory_set" in MEMORY_INSTRUCTIONS

    def test_instructions_describe_routing(self) -> None:
        from ark_agentic.core.prompt.builder import MEMORY_INSTRUCTIONS
        assert "全局" in MEMORY_INSTRUCTIONS or "global" in MEMORY_INSTRUCTIONS.lower()
