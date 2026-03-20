"""Tests for user profile (heading-based markdown) management and injection."""

import tempfile
from pathlib import Path

import pytest

from ark_agentic.core.memory.user_profile import (
    _PROFILES_DIR,
    ensure_user_profile,
    format_heading_sections,
    get_profile_path,
    load_user_profile,
    parse_heading_sections,
    truncate_profile,
    upsert_profile_by_heading,
    write_profile,
)
from ark_agentic.core.paths import get_memory_base_dir
from ark_agentic.core.prompt.builder import SystemPromptBuilder


# ============ parse / format heading sections ============


class TestParseHeadingSections:
    def test_empty_string(self) -> None:
        assert parse_heading_sections("") == {}

    def test_single_heading(self) -> None:
        result = parse_heading_sections("## 姓名\n张三")
        assert result == {"姓名": "张三"}

    def test_multiple_headings(self) -> None:
        text = "## 姓名\n张三\n\n## 偏好\n简洁"
        result = parse_heading_sections(text)
        assert result == {"姓名": "张三", "偏好": "简洁"}

    def test_multiline_content(self) -> None:
        text = "## 基本信息\n姓名: 张三\n角色: 开发者\n\n## 偏好\n简洁"
        result = parse_heading_sections(text)
        assert result["基本信息"] == "姓名: 张三\n角色: 开发者"

    def test_no_headings(self) -> None:
        assert parse_heading_sections("just plain text") == {}


class TestFormatHeadingSections:
    def test_roundtrip(self) -> None:
        sections = {"姓名": "张三", "偏好": "简洁"}
        text = format_heading_sections(sections)
        parsed = parse_heading_sections(text)
        assert parsed == sections

    def test_empty_dict(self) -> None:
        assert format_heading_sections({}) == ""


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


# ============ load_user_profile ============


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
            p = profile_dir / "MEMORY.md"
            p.write_text("## 偏好\npython\n", encoding="utf-8")

            content = load_user_profile(base, "user1")
            assert "python" in content

    def test_empty_file_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            profile_dir = base / _PROFILES_DIR / "user1"
            profile_dir.mkdir(parents=True)
            (profile_dir / "MEMORY.md").write_text("", encoding="utf-8")
            assert load_user_profile(base, "user1") == ""


# ============ ensure_user_profile ============


class TestEnsureUserProfile:
    def test_creates_empty_file_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            path = ensure_user_profile(base, "new_user")
            assert path.exists()
            assert path.read_text(encoding="utf-8") == ""

    def test_does_not_overwrite_existing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            profile_dir = base / _PROFILES_DIR / "user1"
            profile_dir.mkdir(parents=True)
            existing = "## 姓名\n张三\n"
            (profile_dir / "MEMORY.md").write_text(existing, encoding="utf-8")

            path = ensure_user_profile(base, "user1")
            assert path.read_text(encoding="utf-8") == existing


# ============ upsert_profile_by_heading ============


class TestUpsertProfileByHeading:
    def test_insert_new_heading(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            p = Path(tmpdir) / "MEMORY.md"
            p.write_text("## 姓名\n张三\n", encoding="utf-8")
            upsert_profile_by_heading(p, "## 偏好\n简洁")
            sections = parse_heading_sections(p.read_text(encoding="utf-8"))
            assert sections == {"姓名": "张三", "偏好": "简洁"}

    def test_replace_existing_heading(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            p = Path(tmpdir) / "MEMORY.md"
            p.write_text("## 姓名\n张三\n\n## 偏好\n简洁\n", encoding="utf-8")
            upsert_profile_by_heading(p, "## 偏好\n详细")
            sections = parse_heading_sections(p.read_text(encoding="utf-8"))
            assert sections["姓名"] == "张三"
            assert sections["偏好"] == "详细"

    def test_multiple_headings_at_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            p = Path(tmpdir) / "MEMORY.md"
            p.write_text("", encoding="utf-8")
            upsert_profile_by_heading(p, "## 姓名\n张三\n\n## 角色\n开发者")
            sections = parse_heading_sections(p.read_text(encoding="utf-8"))
            assert sections == {"姓名": "张三", "角色": "开发者"}

    def test_creates_file_if_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            p = Path(tmpdir) / "sub" / "MEMORY.md"
            upsert_profile_by_heading(p, "## 姓名\n张三")
            assert p.exists()
            sections = parse_heading_sections(p.read_text(encoding="utf-8"))
            assert sections["姓名"] == "张三"

    def test_no_heading_content_skips(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            p = Path(tmpdir) / "MEMORY.md"
            p.write_text("## 姓名\n张三\n", encoding="utf-8")
            upsert_profile_by_heading(p, "plain text without heading")
            content = p.read_text(encoding="utf-8")
            assert "张三" in content


# ============ write_profile ============


class TestWriteProfile:
    def test_overwrites_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            ensure_user_profile(base, "u1")
            new_content = "## 基本信息\n姓名: Bob\n"
            write_profile(base, "u1", new_content)
            raw = get_profile_path(base, "u1").read_text(encoding="utf-8")
            assert "姓名: Bob" in raw


# ============ truncate_profile ============


class TestTruncateProfile:
    def test_short_content_unchanged(self) -> None:
        content = "## 偏好\npython\n## 时区\nUTC"
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
        builder.add_user_profile("## 偏好\n中文回复\n## 技术水平\n专家")
        prompt = builder.build()
        assert "用户画像" in prompt
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
        assert "用户画像" in prompt
        assert "Asia/Shanghai" in prompt

    def test_quick_build_without_profile(self) -> None:
        prompt = SystemPromptBuilder.quick_build()
        assert "用户画像" not in prompt

    def test_profile_section_order(self) -> None:
        builder = SystemPromptBuilder()
        builder.add_identity(name="Bot")
        builder.add_runtime_info()
        builder.add_user_profile("## 画像\ncontent")
        builder.add_tools([])
        builder.add_memory_instructions()
        prompt = builder.build()

        sections = [name for name, _ in builder._sections]
        profile_idx = sections.index("user_profile")
        identity_idx = sections.index("identity")
        assert profile_idx > identity_idx

        runtime_idx = sections.index("runtime")
        assert profile_idx > runtime_idx
