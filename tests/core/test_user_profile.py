"""Tests for user profile (USER.md) management and injection."""

import tempfile
from pathlib import Path

import pytest

from ark_agentic.core.memory.user_profile import (
    _DEFAULT_SECTIONS,
    _DEFAULT_TEMPLATE,
    _PROFILES_DIR,
    ensure_user_profile,
    get_profile_path,
    load_user_profile,
    truncate_profile,
    upsert_profile_entry,
    write_profile,
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

    def test_template_contains_default_sections(self) -> None:
        for s in _DEFAULT_SECTIONS:
            assert f"## {s}" in _DEFAULT_TEMPLATE


# ============ upsert_profile_entry ============


class TestUpsertProfileEntry:
    def test_insert_into_existing_section(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            ensure_user_profile(base, "u1")
            upsert_profile_entry(base, "u1", "沟通风格", "偏好风格", "专业简洁")
            content = load_user_profile(base, "u1")
            assert "- 偏好风格: 专业简洁" in content

    def test_update_existing_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            ensure_user_profile(base, "u1")
            upsert_profile_entry(base, "u1", "沟通风格", "偏好风格", "温柔活泼")
            upsert_profile_entry(base, "u1", "偏好", "回复长度", "详细")
            upsert_profile_entry(base, "u1", "沟通风格", "偏好风格", "专业简洁")

            content = load_user_profile(base, "u1")
            assert content.count("偏好风格") == 1
            assert "- 偏好风格: 专业简洁" in content
            assert "温柔活泼" not in content
            assert "- 回复长度: 详细" in content

    def test_multiple_keys_in_same_section(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            ensure_user_profile(base, "u1")
            upsert_profile_entry(base, "u1", "基本信息", "姓名", "Willis")
            upsert_profile_entry(base, "u1", "基本信息", "时区", "Asia/Shanghai")
            content = load_user_profile(base, "u1")
            assert "- 姓名: Willis" in content
            assert "- 时区: Asia/Shanghai" in content

    def test_create_new_section(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            ensure_user_profile(base, "u1")
            upsert_profile_entry(base, "u1", "技术偏好", "编程语言", "Python")
            content = load_user_profile(base, "u1")
            assert "## 技术偏好" in content
            assert "- 编程语言: Python" in content

    def test_upsert_in_custom_section(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            ensure_user_profile(base, "u1")
            upsert_profile_entry(base, "u1", "技术偏好", "框架", "FastAPI")
            upsert_profile_entry(base, "u1", "技术偏好", "框架", "Django")
            content = load_user_profile(base, "u1")
            assert content.count("框架") == 1
            assert "- 框架: Django" in content
            assert "FastAPI" not in content

    def test_creates_profile_if_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            upsert_profile_entry(base, "new_u", "偏好", "语言", "中文")
            content = load_user_profile(base, "new_u")
            assert "- 语言: 中文" in content
            assert "用户画像" in content

    def test_preserves_other_sections(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            ensure_user_profile(base, "u1")
            upsert_profile_entry(base, "u1", "基本信息", "姓名", "Alice")
            upsert_profile_entry(base, "u1", "偏好", "回复长度", "简洁")
            content = load_user_profile(base, "u1")
            assert "## 基本信息" in content
            assert "## 偏好" in content
            assert "## 沟通风格" in content
            assert "## 重要事项" in content


# ============ write_profile ============


class TestWriteProfile:
    def test_overwrites_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            ensure_user_profile(base, "u1")
            new_content = "# Clean profile\n## 基本信息\n- 姓名: Bob\n"
            write_profile(base, "u1", new_content)
            assert load_user_profile(base, "u1") == new_content


# ============ truncate_profile ============


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
        assert "USER.md" in tool.description or "profile" in tool.description
        assert len(tool.parameters) == 3

    @pytest.mark.asyncio
    async def test_upsert_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            import os
            os.environ["MEMORY_DIR"] = tmpdir
            try:
                tool = ProfileSetTool()
                call = ToolCall(
                    id="call_1",
                    name="profile_set",
                    arguments={"section": "偏好", "key": "主题", "value": "暗色模式"},
                )
                result = await tool.execute(call, {"user:id": "test_user"})
                assert result.content["status"] == "written"
                assert result.content["section"] == "偏好"
                assert result.content["key"] == "主题"

                content = load_user_profile(Path(tmpdir), "test_user")
                assert "- 主题: 暗色模式" in content
            finally:
                del os.environ["MEMORY_DIR"]

    @pytest.mark.asyncio
    async def test_upsert_overwrites(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            import os
            os.environ["MEMORY_DIR"] = tmpdir
            try:
                tool = ProfileSetTool()
                call1 = ToolCall(
                    id="c1", name="profile_set",
                    arguments={"section": "沟通风格", "key": "偏好风格", "value": "温柔"},
                )
                call2 = ToolCall(
                    id="c2", name="profile_set",
                    arguments={"section": "沟通风格", "key": "偏好风格", "value": "专业简洁"},
                )
                await tool.execute(call1, {"user:id": "u1"})
                await tool.execute(call2, {"user:id": "u1"})

                content = load_user_profile(Path(tmpdir), "u1")
                assert content.count("偏好风格") == 1
                assert "专业简洁" in content
                assert "温柔" not in content
            finally:
                del os.environ["MEMORY_DIR"]

    @pytest.mark.asyncio
    async def test_custom_section(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            import os
            os.environ["MEMORY_DIR"] = tmpdir
            try:
                tool = ProfileSetTool()
                call = ToolCall(
                    id="c1", name="profile_set",
                    arguments={"section": "技术偏好", "key": "语言", "value": "Python"},
                )
                result = await tool.execute(call, {"user:id": "u1"})
                assert result.content["status"] == "written"

                content = load_user_profile(Path(tmpdir), "u1")
                assert "## 技术偏好" in content
                assert "- 语言: Python" in content
            finally:
                del os.environ["MEMORY_DIR"]

    @pytest.mark.asyncio
    async def test_missing_required_fields(self) -> None:
        tool = ProfileSetTool()
        for args in [
            {"section": "偏好", "key": "x", "value": ""},
            {"section": "", "key": "x", "value": "y"},
            {"section": "偏好", "key": "", "value": "y"},
        ]:
            call = ToolCall(id="c1", name="profile_set", arguments=args)
            result = await tool.execute(call, {"user:id": "u1"})
            assert result.result_type.value == "error"

    @pytest.mark.asyncio
    async def test_missing_user_id(self) -> None:
        tool = ProfileSetTool()
        call = ToolCall(
            id="call_1", name="profile_set",
            arguments={"section": "偏好", "key": "x", "value": "y"},
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

    def test_instructions_describe_section_key_value(self) -> None:
        from ark_agentic.core.prompt.builder import MEMORY_INSTRUCTIONS
        assert "section" in MEMORY_INSTRUCTIONS
        assert "key" in MEMORY_INSTRUCTIONS
        assert "value" in MEMORY_INSTRUCTIONS

    def test_instructions_describe_routing(self) -> None:
        from ark_agentic.core.prompt.builder import MEMORY_INSTRUCTIONS
        assert "全局" in MEMORY_INSTRUCTIONS or "global" in MEMORY_INSTRUCTIONS.lower()
