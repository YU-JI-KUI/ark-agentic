"""Tests for skill system."""

import pytest
import tempfile
from pathlib import Path

from ark_agentic.core.skills.base import (
    SkillConfig,
    build_skill_prompt,
    check_skill_requirements,
    format_skills_metadata_for_prompt,
)
from ark_agentic.core.skills.loader import (
    SkillLoader,
    load_skills_from_directory,
)
from ark_agentic.core.skills.matcher import SkillMatcher
from ark_agentic.core.types import SkillEntry, SkillMetadata


class TestSkillConfig:
    """Tests for SkillConfig."""

    def test_default_values(self) -> None:
        """Test default configuration values."""
        config = SkillConfig()
        assert config.skill_directories == []
        assert config.default_invocation_policy == "auto"

    def test_custom_directories(self) -> None:
        """Test custom directories."""
        config = SkillConfig(skill_directories=["/path/to/skills"])
        assert config.skill_directories == ["/path/to/skills"]


class TestCheckSkillRequirements:
    """Tests for skill requirement checking."""

    def test_no_requirements(self) -> None:
        """Test skill with no requirements."""
        skill = SkillEntry(
            id="test",
            path="/test",
            content="Test content",
            metadata=SkillMetadata(name="test", description="Test"),
        )
        is_eligible, reasons = check_skill_requirements(skill)
        assert is_eligible
        assert len(reasons) == 0

    def test_os_requirement_match(self) -> None:
        """Test matching OS requirement."""
        import platform
        current_os = platform.system().lower()

        skill = SkillEntry(
            id="test",
            path="/test",
            content="Test content",
            metadata=SkillMetadata(
                name="test",
                description="Test",
                required_os=[current_os]
            ),
        )
        is_eligible, reasons = check_skill_requirements(skill)
        assert is_eligible
        assert len(reasons) == 0

    def test_os_requirement_mismatch(self) -> None:
        """Test mismatching OS requirement."""
        skill = SkillEntry(
            id="test",
            path="/test",
            content="Test content",
            metadata=SkillMetadata(
                name="test",
                description="Test",
                required_os=["nonexistent_os"]
            ),
        )
        is_eligible, reasons = check_skill_requirements(skill)
        assert not is_eligible
        assert len(reasons) > 0


class TestFormatSkillsMetadataForPrompt:
    """Tests for format_skills_metadata_for_prompt (metadata-only, no full content)."""

    def test_empty_skills(self) -> None:
        """Test with no skills."""
        assert format_skills_metadata_for_prompt([]) == ""

    def test_single_skill_metadata_only(self) -> None:
        """Output contains id, name, description (when_to_use merged in) but NOT skill content."""
        skill = SkillEntry(
            id="test",
            path="/test",
            content="This is the full skill body that must not appear.",
            metadata=SkillMetadata(
                name="Test Skill",
                description="A test\nWhen to use: When user asks for X",
            ),
        )
        prompt = format_skills_metadata_for_prompt([skill])
        assert "test" in prompt
        assert "Test Skill" in prompt
        assert "A test" in prompt
        assert "When user asks for X" in prompt
        assert "This is the full skill body that must not appear." not in prompt

    def test_multiple_skills_metadata_only(self) -> None:
        """Multiple skills: metadata list only, no content."""
        skills = [
            SkillEntry(
                id="skill1",
                path="/skill1",
                content="Secret content 1",
                metadata=SkillMetadata(name="Skill 1", description="First\nWhen to use: When A"),
            ),
            SkillEntry(
                id="skill2",
                path="/skill2",
                content="Secret content 2",
                metadata=SkillMetadata(name="Skill 2", description="Second"),
            ),
        ]
        prompt = format_skills_metadata_for_prompt(skills)
        assert "skill1" in prompt and "Skill 1" in prompt and "When A" in prompt
        assert "skill2" in prompt and "Skill 2" in prompt
        assert "Secret content 1" not in prompt
        assert "Secret content 2" not in prompt


class TestBuildSkillPrompt:
    """Tests for skill prompt building."""

    def test_empty_skills(self) -> None:
        """Test with no skills."""
        prompt = build_skill_prompt([])
        assert prompt == ""

    def test_single_skill(self) -> None:
        """Test with single skill."""
        skill = SkillEntry(
            id="test",
            path="/test",
            content="This is the skill content.",
            metadata=SkillMetadata(name="Test Skill", description="A test"),
        )
        prompt = build_skill_prompt([skill])
        assert "Test Skill" in prompt
        assert "This is the skill content." in prompt

    def test_multiple_skills(self) -> None:
        """Test with multiple skills."""
        skills = [
            SkillEntry(
                id="skill1",
                path="/skill1",
                content="Content 1",
                metadata=SkillMetadata(name="Skill 1", description="First"),
            ),
            SkillEntry(
                id="skill2",
                path="/skill2",
                content="Content 2",
                metadata=SkillMetadata(name="Skill 2", description="Second"),
            ),
        ]
        prompt = build_skill_prompt(skills)
        assert "Skill 1" in prompt
        assert "Skill 2" in prompt
        assert "Content 1" in prompt
        assert "Content 2" in prompt


class TestSkillLoader:
    """Tests for SkillLoader."""

    def _create_skill_directory(self, tmpdir: str, skill_id: str, content: str, frontmatter: str = "") -> None:
        """Create a skill directory with SKILL.md."""
        skill_dir = Path(tmpdir) / skill_id
        skill_dir.mkdir(parents=True)

        skill_content = content
        if frontmatter:
            skill_content = f"---\n{frontmatter}\n---\n\n{content}"

        (skill_dir / "SKILL.md").write_text(skill_content)

    def test_load_from_empty_directory(self) -> None:
        """Test loading from empty directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            loader = SkillLoader(SkillConfig(skill_directories=[tmpdir]))
            skills = loader.load_from_directories()
            assert skills == {}

    def test_load_single_skill(self) -> None:
        """Test loading single skill."""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._create_skill_directory(
                tmpdir,
                "test_skill",
                "This is the skill content.",
                "name: Test Skill\ndescription: A test skill"
            )

            loader = SkillLoader(SkillConfig(skill_directories=[tmpdir]))
            skills = loader.load_from_directories()

            assert "test_skill" in skills
            skill = skills["test_skill"]
            assert skill.metadata.name == "Test Skill"
            assert "This is the skill content." in skill.content

    def test_load_skill_with_when_to_use(self) -> None:
        """Test loading skill with when_to_use in frontmatter: merged into description."""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._create_skill_directory(
                tmpdir,
                "withdraw_money",
                "Full skill body here.",
                "name: Withdraw\ndescription: Withdraw money\nwhen_to_use: When user asks to withdraw or surrender"
            )

            loader = SkillLoader(SkillConfig(skill_directories=[tmpdir]))
            skills = loader.load_from_directories()

            assert "withdraw_money" in skills
            skill = skills["withdraw_money"]
            assert "When to use:" in skill.metadata.description
            assert "When user asks to withdraw or surrender" in skill.metadata.description
            assert "Full skill body here." in skill.content

    def test_load_skill_without_frontmatter(self) -> None:
        """Test loading skill without YAML frontmatter."""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._create_skill_directory(
                tmpdir,
                "simple_skill",
                "Just the content, no frontmatter."
            )

            loader = SkillLoader(SkillConfig(skill_directories=[tmpdir]))
            skills = loader.load_from_directories()

            assert "simple_skill" in skills
            # Name defaults to skill_id
            assert skills["simple_skill"].metadata.name == "simple_skill"

    def test_load_multiple_skills(self) -> None:
        """Test loading multiple skills."""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._create_skill_directory(tmpdir, "skill1", "Content 1")
            self._create_skill_directory(tmpdir, "skill2", "Content 2")

            loader = SkillLoader(SkillConfig(skill_directories=[tmpdir]))
            skills = loader.load_from_directories()

            assert len(skills) == 2
            assert "skill1" in skills
            assert "skill2" in skills

    def test_priority_override(self) -> None:
        """Test skill override by priority."""
        with tempfile.TemporaryDirectory() as tmpdir1:
            with tempfile.TemporaryDirectory() as tmpdir2:
                # Create same skill in both directories
                self._create_skill_directory(tmpdir1, "shared", "Content from dir1")
                self._create_skill_directory(tmpdir2, "shared", "Content from dir2")

                # Lower priority directory first
                loader = SkillLoader(SkillConfig(skill_directories=[tmpdir1, tmpdir2]))
                skills = loader.load_from_directories()

                # Should use content from first directory (lower index = lower priority = wins)
                assert "Content from dir1" in skills["shared"].content

    def test_get_skill(self) -> None:
        """Test getting specific skill."""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._create_skill_directory(tmpdir, "test", "Test content")

            loader = SkillLoader(SkillConfig(skill_directories=[tmpdir]))
            loader.load_from_directories()

            skill = loader.get_skill("test")
            assert skill is not None
            assert skill.id == "test"

            assert loader.get_skill("nonexistent") is None

    def test_list_skills(self) -> None:
        """Test listing skills."""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._create_skill_directory(tmpdir, "skill1", "Content 1")
            self._create_skill_directory(tmpdir, "skill2", "Content 2")

            loader = SkillLoader(SkillConfig(skill_directories=[tmpdir]))
            loader.load_from_directories()

            skills = loader.list_skills()
            assert len(skills) == 2

            ids = loader.list_skill_ids()
            assert set(ids) == {"skill1", "skill2"}

    def test_reload(self) -> None:
        """Test reloading skills."""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._create_skill_directory(tmpdir, "skill1", "Original content")

            loader = SkillLoader(SkillConfig(skill_directories=[tmpdir]))
            loader.load_from_directories()

            # Modify skill
            (Path(tmpdir) / "skill1" / "SKILL.md").write_text("Updated content")

            loader.reload()
            assert "Updated content" in loader.get_skill("skill1").content


class TestLoadSkillsFromDirectory:
    """Tests for convenience function."""

    def test_load_skills_from_directory(self) -> None:
        """Test loading from single directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = Path(tmpdir) / "test_skill"
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text("Test content")

            skills = load_skills_from_directory(tmpdir)
            assert "test_skill" in skills


class TestSkillMatcher:
    """Tests for SkillMatcher."""

    def _create_loader_with_skills(self, tmpdir: str, skills_data: list[dict]) -> SkillLoader:
        """Create a loader with test skills."""
        for skill_data in skills_data:
            skill_dir = Path(tmpdir) / skill_data["id"]
            skill_dir.mkdir(parents=True)

            frontmatter = f"name: {skill_data.get('name', skill_data['id'])}\n"
            frontmatter += f"description: {skill_data.get('description', '')}\n"
            if "policy" in skill_data:
                frontmatter += f"invocation_policy: {skill_data['policy']}\n"
            if "tags" in skill_data:
                frontmatter += f"tags: {skill_data['tags']}\n"

            content = f"---\n{frontmatter}---\n\n{skill_data.get('content', 'Content')}"
            (skill_dir / "SKILL.md").write_text(content)

        loader = SkillLoader(SkillConfig(skill_directories=[tmpdir]))
        loader.load_from_directories()
        return loader

    def test_match_always_skills(self) -> None:
        """Test matching skills with 'always' policy."""
        with tempfile.TemporaryDirectory() as tmpdir:
            loader = self._create_loader_with_skills(tmpdir, [
                {"id": "always_skill", "policy": "always"},
                {"id": "auto_skill", "policy": "auto"},
            ])

            matcher = SkillMatcher(loader)
            result = matcher.match()

            # 'always' skills should always be included
            skill_ids = [s.id for s in result.matched_skills]
            assert "always_skill" in skill_ids

    def test_match_auto_skills(self) -> None:
        """Test matching skills with 'auto' policy."""
        with tempfile.TemporaryDirectory() as tmpdir:
            loader = self._create_loader_with_skills(tmpdir, [
                {"id": "auto_skill", "policy": "auto"},
            ])

            matcher = SkillMatcher(loader)
            result = matcher.match()

            # 'auto' skills should be matched
            skill_ids = [s.id for s in result.matched_skills]
            assert "auto_skill" in skill_ids

    def test_match_manual_skills_not_included(self) -> None:
        """Test that manual skills are not auto-included."""
        with tempfile.TemporaryDirectory() as tmpdir:
            loader = self._create_loader_with_skills(tmpdir, [
                {"id": "manual_skill", "policy": "manual"},
            ])

            matcher = SkillMatcher(loader)
            result = matcher.match()

            skill_ids = [s.id for s in result.matched_skills]
            assert "manual_skill" not in skill_ids

    def test_match_by_explicit_ids(self) -> None:
        """Test matching by explicit skill IDs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            loader = self._create_loader_with_skills(tmpdir, [
                {"id": "skill1"},
                {"id": "skill2"},
                {"id": "skill3"},
            ])

            matcher = SkillMatcher(loader)
            result = matcher.match(skill_ids=["skill1", "skill3"])

            skill_ids = [s.id for s in result.matched_skills]
            assert set(skill_ids) == {"skill1", "skill3"}
