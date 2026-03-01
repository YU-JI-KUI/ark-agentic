import json
import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from fastapi import FastAPI

from ark_agentic.studio.api.skills import router as skills_router, _parse_skill_md

app = FastAPI()
app.include_router(skills_router)
client = TestClient(app)

@pytest.fixture
def mock_agents_root(tmp_path, monkeypatch):
    """Mock the _agents_root function to return a temp directory."""
    def mock_root():
        return tmp_path
    monkeypatch.setattr("ark_agentic.studio.api.skills._agents_root", mock_root)
    return tmp_path

def test_parse_skill_md_with_frontmatter(tmp_path):
    skill_dir = tmp_path / "test_skill"
    skill_dir.mkdir()
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(
        "---\nname: Test Skill\ndescription: 'This is a test skill'\n---\n# Content starts here\n",
        encoding="utf-8"
    )

    meta = _parse_skill_md(skill_dir)
    assert meta is not None
    assert meta.id == "test_skill"
    assert meta.name == "Test Skill"
    assert meta.description == "This is a test skill"
    assert meta.content.startswith("---")
    # assert relative path correctly - but relative_to(skill_dir.parent.parent) in code: 
    # file_path=str(skill_file.relative_to(skill_dir.parent.parent))
    # tmp_path / test_skill / SKILL.md. parent.parent is tmp_path. relative is test_skill/SKILL.md
    assert "test_skill/SKILL.md" in meta.file_path.replace("\\", "/")

def test_parse_skill_md_no_frontmatter(tmp_path):
    skill_dir = tmp_path / "skill2"
    skill_dir.mkdir()
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text("# Just content\n", encoding="utf-8")

    meta = _parse_skill_md(skill_dir)
    assert meta is not None
    assert meta.id == "skill2"
    assert meta.name == "skill2" # fallback to dir name
    assert meta.description == ""

def test_parse_skill_md_not_found(tmp_path):
    skill_dir = tmp_path / "empty_skill"
    skill_dir.mkdir()
    assert _parse_skill_md(skill_dir) is None

def test_list_skills_success(mock_agents_root):
    # Setup agent dir
    agent_dir = mock_agents_root / "agent1"
    agent_dir.mkdir()
    skills_dir = agent_dir / "skills"
    skills_dir.mkdir()

    # Setup valid skill
    skill1_dir = skills_dir / "skill1"
    skill1_dir.mkdir()
    (skill1_dir / "SKILL.md").write_text("---\nname: Skill 1\n---\nData", encoding="utf-8")

    # Setup invalid skill
    invalid_skill_dir = skills_dir / "invalid"
    invalid_skill_dir.mkdir()

    # Setup hidden dir
    (skills_dir / "_hidden").mkdir()

    response = client.get("/agents/agent1/skills")
    assert response.status_code == 200
    data = response.json()
    assert len(data["skills"]) == 1
    assert data["skills"][0]["name"] == "Skill 1"

def test_list_skills_agent_not_found(mock_agents_root):
    response = client.get("/agents/missing_agent/skills")
    assert response.status_code == 404
