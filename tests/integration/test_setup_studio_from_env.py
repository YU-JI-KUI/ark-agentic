"""
Acceptance tests for setup_studio_from_env() and API_APP_TEMPLATE Studio integration.

Covers:
  - setup_studio_from_env: env=false skips, env=true delegates to setup_studio
  - setup_studio_from_env: ImportError and generic Exception are handled gracefully
  - API_APP_TEMPLATE: setup_studio_from_env called at module level, no ENABLE_STUDIO in lifespan
  - CLI --api: generated app.py has Studio support built-in
  - CLI add-agent: also generates agent.json
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI


# ── setup_studio_from_env: env gate ──────────────────────────────────────────

def test_setup_studio_from_env_disabled_by_default(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("ENABLE_STUDIO", raising=False)
    from ark_agentic.studio import setup_studio_from_env
    app = FastAPI()
    with patch("ark_agentic.studio.setup_studio") as mock_setup:
        result = setup_studio_from_env(app)
    assert result is False
    mock_setup.assert_not_called()


def test_setup_studio_from_env_disabled_explicitly(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ENABLE_STUDIO", "false")
    from ark_agentic.studio import setup_studio_from_env
    app = FastAPI()
    with patch("ark_agentic.studio.setup_studio") as mock_setup:
        result = setup_studio_from_env(app)
    assert result is False
    mock_setup.assert_not_called()


def test_setup_studio_from_env_enabled_delegates_to_setup_studio(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ENABLE_STUDIO", "true")
    from ark_agentic.studio import setup_studio_from_env
    app = FastAPI()
    registry = MagicMock()
    with patch("ark_agentic.studio.setup_studio") as mock_setup:
        result = setup_studio_from_env(app, registry=registry)
    assert result is True
    mock_setup.assert_called_once_with(app, registry=registry)


def test_setup_studio_from_env_enabled_no_registry(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ENABLE_STUDIO", "true")
    from ark_agentic.studio import setup_studio_from_env
    app = FastAPI()
    with patch("ark_agentic.studio.setup_studio") as mock_setup:
        result = setup_studio_from_env(app)
    assert result is True
    mock_setup.assert_called_once_with(app, registry=None)


# ── setup_studio_from_env: error handling ────────────────────────────────────

def test_setup_studio_from_env_import_error_is_caught(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ENABLE_STUDIO", "true")
    from ark_agentic.studio import setup_studio_from_env
    app = FastAPI()
    with patch("ark_agentic.studio.setup_studio", side_effect=ImportError("no module")):
        result = setup_studio_from_env(app)
    assert result is True


def test_setup_studio_from_env_generic_exception_is_caught(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ENABLE_STUDIO", "true")
    from ark_agentic.studio import setup_studio_from_env
    app = FastAPI()
    with patch("ark_agentic.studio.setup_studio", side_effect=RuntimeError("boom")):
        result = setup_studio_from_env(app)
    assert result is True


# ── API_APP_TEMPLATE contract ────────────────────────────────────────────────

def _render_api_template() -> str:
    from ark_agentic.cli.templates import API_APP_TEMPLATE
    return API_APP_TEMPLATE.format(
        project_name="TestProj",
        package_name="test_proj",
        agent_name="default",
        agent_name_snake="default",
        agent_display_name="Default",
    )


def test_api_template_imports_setup_studio_from_env():
    rendered = _render_api_template()
    assert "from ark_agentic.studio import setup_studio_from_env" in rendered


def test_api_template_calls_setup_studio_from_env_at_module_level():
    rendered = _render_api_template()
    lifespan_end = rendered.index("yield")
    studio_call_pos = rendered.index("setup_studio_from_env(app")
    assert studio_call_pos > lifespan_end, (
        "setup_studio_from_env should be called AFTER lifespan (at module level)"
    )


def test_api_template_no_enable_studio_env_check_in_lifespan():
    rendered = _render_api_template()
    lifespan_start = rendered.index("async def lifespan")
    app_def_start = rendered.index("app = FastAPI(")
    lifespan_body = rendered[lifespan_start:app_def_start]
    assert "ENABLE_STUDIO" not in lifespan_body
    assert "setup_studio" not in lifespan_body


def test_api_template_uvicorn_entry_point():
    rendered = _render_api_template()
    assert '"test_proj.app:app"' in rendered


# ── CLI --api generates correct app.py ───────────────────────────────────────

def test_cmd_init_with_api_creates_app_py_with_studio(tmp_path: Path):
    """init --api generates app.py with setup_studio_from_env built-in."""
    from ark_agentic.cli.main import _cmd_init
    args = type("Args", (), {
        "project_name": "myproj",
        "api": True,
        "memory": False,
        "llm_provider": "openai",
    })()
    with patch.object(Path, "cwd", return_value=tmp_path):
        _cmd_init(args)

    app_py = (tmp_path / "myproj" / "src" / "myproj" / "app.py").read_text(encoding="utf-8")
    assert "setup_studio_from_env" in app_py
    assert "ENABLE_STUDIO" not in app_py
    assert "AgentRegistry" in app_py
    assert "chat_api" in app_py


def test_cmd_init_with_api_has_agent_json(tmp_path: Path):
    """init --api also creates agent.json for Studio discovery."""
    from ark_agentic.cli.main import _cmd_init
    args = type("Args", (), {
        "project_name": "myproj",
        "api": True,
        "memory": False,
        "llm_provider": "openai",
    })()
    with patch.object(Path, "cwd", return_value=tmp_path):
        _cmd_init(args)

    agent_json = tmp_path / "myproj" / "src" / "myproj" / "agents" / "default" / "agent.json"
    assert agent_json.is_file(), "agent.json must be created for Studio discovery"


def test_cmd_init_without_api_also_has_agent_json(tmp_path: Path):
    """Even without --api, agent.json is generated (for future Studio use)."""
    from ark_agentic.cli.main import _cmd_init
    args = type("Args", (), {
        "project_name": "myproj",
        "api": False,
        "memory": False,
        "llm_provider": "openai",
    })()
    with patch.object(Path, "cwd", return_value=tmp_path):
        _cmd_init(args)

    agent_json = tmp_path / "myproj" / "src" / "myproj" / "agents" / "default" / "agent.json"
    assert agent_json.is_file()


# ── CLI add-agent generates agent.json ───────────────────────────────────────

def test_cmd_add_agent_generates_agent_json(tmp_path: Path):
    """add-agent must also generate agent.json for Studio discovery."""
    from ark_agentic.cli.main import _cmd_init, _cmd_add_agent

    init_args = type("Args", (), {
        "project_name": "myproj",
        "api": True,
        "memory": False,
        "llm_provider": "openai",
    })()
    with patch.object(Path, "cwd", return_value=tmp_path):
        _cmd_init(init_args)

    add_args = type("Args", (), {"agent_name": "billing"})()
    proj_root = tmp_path / "myproj"
    with patch.object(Path, "cwd", return_value=proj_root):
        _cmd_add_agent(add_args)

    agent_json = proj_root / "src" / "myproj" / "agents" / "billing" / "agent.json"
    assert agent_json.is_file(), "add-agent must generate agent.json"
    content = agent_json.read_text(encoding="utf-8")
    assert '"billing"' in content
