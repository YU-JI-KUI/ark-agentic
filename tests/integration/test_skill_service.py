"""
Skill Service tests — 直接测试 Service 层，不依赖 FastAPI。
"""

import pytest
import tempfile
from pathlib import Path

from ark_agentic.plugins.studio.services.skill_service import (
    create_skill,
    update_skill,
    delete_skill,
    list_skills,
    slugify,
    generate_skill_md,
    parse_skill_dir,
)


@pytest.fixture
def agents_root(tmp_path: Path) -> Path:
    """创建临时 Agent 目录结构。"""
    agent_dir = tmp_path / "test_agent" / "skills"
    agent_dir.mkdir(parents=True)
    return tmp_path


@pytest.fixture
def seeded_root(agents_root: Path) -> Path:
    """预置一个 Skill 的 Agent 目录。"""
    skill_dir = agents_root / "test_agent" / "skills" / "existing_skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: Existing\ndescription: A test skill\n---\n\n# Content here\n",
        encoding="utf-8",
    )
    return agents_root


# ── Slugify ─────────────────────────────────────────────────────────

def test_slugify_basic():
    assert slugify("hello world") == "hello-world"

def test_slugify_chinese():
    assert slugify("需求澄清") == "需求澄清"

def test_slugify_dangerous():
    assert slugify("../../etc") == "etc"

def test_slugify_empty_raises():
    with pytest.raises(ValueError):
        slugify("...")


# ── Generate ────────────────────────────────────────────────────────

def test_generate_skill_md_basic():
    md = generate_skill_md("Test", "A test", "# Hello")
    assert "---" in md
    assert "name: Test" in md
    assert "description: A test" in md
    assert "# Hello" in md


# ── Create ──────────────────────────────────────────────────────────

def test_create_skill(agents_root):
    meta = create_skill(agents_root, "test_agent", "New Skill", "desc", "# Content")
    assert meta.name == "New Skill"
    assert meta.id == "New-Skill"
    assert "---" in meta.content

    # 文件系统验证
    skill_dir = agents_root / "test_agent" / "skills" / "New-Skill"
    assert skill_dir.is_dir()
    assert (skill_dir / "SKILL.md").is_file()


def test_create_skill_duplicate_raises(seeded_root):
    with pytest.raises(FileExistsError):
        create_skill(seeded_root, "test_agent", "existing_skill")


def test_create_skill_empty_name_raises(agents_root):
    with pytest.raises(ValueError):
        create_skill(agents_root, "test_agent", "")


def test_create_skill_agent_not_found(agents_root):
    with pytest.raises(FileNotFoundError):
        create_skill(agents_root, "nonexistent", "test")


# ── Update ──────────────────────────────────────────────────────────

def test_update_skill_content(seeded_root):
    meta = update_skill(seeded_root, "test_agent", "existing_skill", content="# Updated")
    assert "# Updated" in meta.content
    assert meta.name == "Existing"


def test_update_skill_name(seeded_root):
    meta = update_skill(seeded_root, "test_agent", "existing_skill", name="Renamed")
    assert meta.name == "Renamed"
    assert "name: Renamed" in meta.content


def test_update_skill_not_found(agents_root):
    with pytest.raises(FileNotFoundError):
        update_skill(agents_root, "test_agent", "nonexistent")


# ── Delete ──────────────────────────────────────────────────────────

def test_delete_skill(seeded_root):
    delete_skill(seeded_root, "test_agent", "existing_skill")
    assert not (seeded_root / "test_agent" / "skills" / "existing_skill").exists()


def test_delete_skill_not_found(agents_root):
    with pytest.raises(FileNotFoundError):
        delete_skill(agents_root, "test_agent", "nonexistent")


# ── List ────────────────────────────────────────────────────────────

def test_list_skills_empty(agents_root):
    skills = list_skills(agents_root, "test_agent")
    assert skills == []


def test_list_skills_with_data(seeded_root):
    skills = list_skills(seeded_root, "test_agent")
    assert len(skills) == 1
    assert skills[0].name == "Existing"


def test_list_skills_agent_not_found(agents_root):
    with pytest.raises(FileNotFoundError):
        list_skills(agents_root, "nonexistent")
