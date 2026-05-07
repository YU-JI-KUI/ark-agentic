"""Tests for user profile (heading-based markdown) management and injection."""

import tempfile
from pathlib import Path

import pytest

from ark_agentic.core.memory.user_profile import (
    _PROFILES_DIR,
    format_heading_sections,
    get_profile_path,
    parse_heading_sections,
    truncate_profile,
    upsert_profile_by_heading,
)
from ark_agentic.core.paths import (
    get_agent_config_file,
    get_config_base_dir,
    get_memory_base_dir,
)
from ark_agentic.core.prompt.builder import SystemPromptBuilder


# ============ parse / format heading sections ============


class TestParseHeadingSections:
    def test_empty_string(self) -> None:
        preamble, sections = parse_heading_sections("")
        assert preamble == ""
        assert sections == {}

    def test_single_heading(self) -> None:
        preamble, sections = parse_heading_sections("## 姓名\n张三")
        assert preamble == ""
        assert sections == {"姓名": "张三"}

    def test_multiple_headings(self) -> None:
        text = "## 姓名\n张三\n\n## 偏好\n简洁"
        preamble, sections = parse_heading_sections(text)
        assert preamble == ""
        assert sections == {"姓名": "张三", "偏好": "简洁"}

    def test_multiline_content(self) -> None:
        text = "## 基本信息\n姓名: 张三\n角色: 开发者\n\n## 偏好\n简洁"
        _, sections = parse_heading_sections(text)
        assert sections["基本信息"] == "姓名: 张三\n角色: 开发者"

    def test_no_headings(self) -> None:
        preamble, sections = parse_heading_sections("just plain text")
        assert preamble == "just plain text"
        assert sections == {}

    def test_preamble_preserved(self) -> None:
        text = "# Agent Memory\n\n此文件用于存储长期记忆。\n\n## 偏好\n简洁"
        preamble, sections = parse_heading_sections(text)
        assert preamble == "# Agent Memory\n\n此文件用于存储长期记忆。"
        assert sections == {"偏好": "简洁"}


class TestFormatHeadingSections:
    def test_roundtrip(self) -> None:
        sections = {"姓名": "张三", "偏好": "简洁"}
        text = format_heading_sections("", sections)
        _, parsed = parse_heading_sections(text)
        assert parsed == sections

    def test_empty_dict(self) -> None:
        assert format_heading_sections("", {}) == ""

    def test_preamble_roundtrip(self) -> None:
        preamble = "# Agent Memory\n\n描述"
        sections = {"偏好": "简洁"}
        text = format_heading_sections(preamble, sections)
        p2, s2 = parse_heading_sections(text)
        assert p2 == preamble
        assert s2 == sections


# ============ get_profile_path ============


class TestGetProfilePath:
    def test_returns_correct_path(self) -> None:
        base = Path("/data/ark_memory")
        path = get_profile_path(base, "user_123")
        assert path == base / _PROFILES_DIR / "user_123" / "MEMORY.md"

    def test_profiles_dir_isolation(self) -> None:
        base = Path("/data/ark_memory")
        profile = get_profile_path(base, "alice")
        agent_dir = base / "insurance" / "alice"
        assert _PROFILES_DIR in str(profile)
        assert str(profile).startswith(str(base / _PROFILES_DIR))
        assert not str(profile).startswith(str(agent_dir))


# ============ upsert_profile_by_heading ============


class TestUpsertProfileByHeading:
    def test_insert_new_heading(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            p = Path(tmpdir) / "MEMORY.md"
            p.write_text("## 姓名\n张三\n", encoding="utf-8")
            upsert_profile_by_heading(p, "## 偏好\n简洁")
            _, sections = parse_heading_sections(p.read_text(encoding="utf-8"))
            assert sections == {"姓名": "张三", "偏好": "简洁"}

    def test_replace_existing_heading(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            p = Path(tmpdir) / "MEMORY.md"
            p.write_text("## 姓名\n张三\n\n## 偏好\n简洁\n", encoding="utf-8")
            upsert_profile_by_heading(p, "## 偏好\n详细")
            _, sections = parse_heading_sections(p.read_text(encoding="utf-8"))
            assert sections["姓名"] == "张三"
            assert sections["偏好"] == "详细"

    def test_multiple_headings_at_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            p = Path(tmpdir) / "MEMORY.md"
            p.write_text("", encoding="utf-8")
            upsert_profile_by_heading(p, "## 姓名\n张三\n\n## 角色\n开发者")
            _, sections = parse_heading_sections(p.read_text(encoding="utf-8"))
            assert sections == {"姓名": "张三", "角色": "开发者"}

    def test_creates_file_if_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            p = Path(tmpdir) / "sub" / "MEMORY.md"
            upsert_profile_by_heading(p, "## 姓名\n张三")
            assert p.exists()
            _, sections = parse_heading_sections(p.read_text(encoding="utf-8"))
            assert sections["姓名"] == "张三"

    def test_no_heading_content_skips(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            p = Path(tmpdir) / "MEMORY.md"
            p.write_text("## 姓名\n张三\n", encoding="utf-8")
            upsert_profile_by_heading(p, "plain text without heading")
            content = p.read_text(encoding="utf-8")
            assert "张三" in content

    def test_preserves_preamble(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            p = Path(tmpdir) / "MEMORY.md"
            p.write_text("# Agent Memory\n\n此文件存储长期记忆。\n\n## 姓名\n张三\n", encoding="utf-8")
            upsert_profile_by_heading(p, "## 偏好\n简洁")
            content = p.read_text(encoding="utf-8")
            assert "# Agent Memory" in content
            assert "此文件存储长期记忆" in content
            _, sections = parse_heading_sections(content)
            assert sections == {"姓名": "张三", "偏好": "简洁"}


# ============ truncate_profile ============


class TestTruncateProfile:
    def test_short_content_unchanged(self) -> None:
        content = "## 偏好\npython\n## 时区\nUTC"
        assert truncate_profile(content, max_tokens=1000) == content

    def test_empty_content(self) -> None:
        assert truncate_profile("", max_tokens=100) == ""

    def test_long_content_truncated(self) -> None:
        sections = [f"## section{i}\ncontent " * 50 for i in range(20)]
        long_content = "\n\n".join(sections)
        result = truncate_profile(long_content, max_tokens=100)
        assert len(result) < len(long_content)

    def test_heading_aware_preserves_priority(self) -> None:
        content = "## 身份信息\n张三\n\n## 回复风格\n简洁\n\n## 杂项\n" + "长内容 " * 500
        result = truncate_profile(content, max_tokens=50)
        assert "张三" in result
        assert "简洁" in result


# ============ paths.py ============


class TestGetMemoryBaseDir:
    def test_default_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MEMORY_DIR", raising=False)
        assert get_memory_base_dir() == Path("data/ark_memory")

    def test_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MEMORY_DIR", "/custom/memory")
        assert get_memory_base_dir() == Path("/custom/memory")


class TestGetConfigBaseDir:
    def test_default_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CONFIG_DIR", raising=False)
        assert get_config_base_dir() == Path("data/ark_config")

    def test_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CONFIG_DIR", "/custom/config")
        assert get_agent_config_file("insurance") == (
            Path("/custom/config") / "insurance" / "agent.json"
        )


# ============ SystemPromptBuilder.add_user_profile ============


class TestBuilderUserProfile:
    def test_add_user_profile(self) -> None:
        builder = SystemPromptBuilder()
        builder.add_user_profile("## 偏好\n中文回复\n## 技术水平\n专家")
        prompt = builder.build()
        assert "<memory_context>" in prompt
        assert "</memory_context>" in prompt
        assert "中文回复" in prompt
        assert "专家" in prompt

    def test_add_user_profile_empty(self) -> None:
        builder = SystemPromptBuilder()
        builder.add_user_profile("")
        assert len(builder._sections) == 0

    def test_quick_build_with_profile(self) -> None:
        prompt = SystemPromptBuilder.quick_build(
            user_profile_content="## 时区\nAsia/Shanghai"
        )
        assert "<memory_context>" in prompt
        assert "Asia/Shanghai" in prompt

    def test_quick_build_without_profile(self) -> None:
        prompt = SystemPromptBuilder.quick_build()
        assert "<user_profile>" not in prompt

    def test_quick_build_memory_enabled(self) -> None:
        prompt = SystemPromptBuilder.quick_build(enable_memory=True)
        assert "<auto_memory_instructions>" in prompt

    def test_quick_build_memory_disabled_by_default(self) -> None:
        prompt = SystemPromptBuilder.quick_build()
        assert "<auto_memory_instructions>" not in prompt

    def test_profile_section_order(self) -> None:
        builder = SystemPromptBuilder()
        builder.add_identity(name="Bot")
        builder.add_runtime_info()
        builder.add_memory_instructions()
        builder.add_user_profile("## 画像\ncontent")
        builder.build()

        sections = [name for name, _ in builder._sections]
        memory_idx = sections.index("auto_memory_instructions")
        identity_idx = sections.index("identity")
        assert memory_idx > identity_idx

        runtime_idx = sections.index("runtime")
        assert memory_idx > runtime_idx
