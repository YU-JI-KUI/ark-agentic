"""
Acceptance tests for setup_studio_from_env() and the CLI scaffold's Studio integration.

Covers:
  - setup_studio_from_env: env=false skips, env=true delegates to setup_studio
  - setup_studio_from_env: ImportError and generic Exception are handled gracefully
  - API_APP_TEMPLATE: Studio enablement happens via Bootstrap + plugin list
    (StudioPlugin gates itself on ENABLE_STUDIO), not via a hand-rolled
    setup_studio_from_env call inside the scaffold.
  - CLI add-agent: generates agent.json for Studio discovery.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI


# ── setup_studio_from_env: env gate ──────────────────────────────────────────

def test_setup_studio_from_env_disabled_by_default(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("ENABLE_STUDIO", raising=False)
    from ark_agentic.plugins.studio import setup_studio_from_env
    app = FastAPI()
    with patch("ark_agentic.plugins.studio.setup_studio") as mock_setup:
        result = setup_studio_from_env(app)
    assert result is False
    mock_setup.assert_not_called()


def test_setup_studio_from_env_disabled_explicitly(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ENABLE_STUDIO", "false")
    from ark_agentic.plugins.studio import setup_studio_from_env
    app = FastAPI()
    with patch("ark_agentic.plugins.studio.setup_studio") as mock_setup:
        result = setup_studio_from_env(app)
    assert result is False
    mock_setup.assert_not_called()


def test_setup_studio_from_env_enabled_delegates_to_setup_studio(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ENABLE_STUDIO", "true")
    from ark_agentic.plugins.studio import setup_studio_from_env
    app = FastAPI()
    registry = MagicMock()
    with patch("ark_agentic.plugins.studio.setup_studio") as mock_setup:
        result = setup_studio_from_env(app, registry=registry)
    assert result is True
    mock_setup.assert_called_once_with(app, registry=registry)


def test_setup_studio_from_env_enabled_no_registry(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ENABLE_STUDIO", "true")
    from ark_agentic.plugins.studio import setup_studio_from_env
    app = FastAPI()
    with patch("ark_agentic.plugins.studio.setup_studio") as mock_setup:
        result = setup_studio_from_env(app)
    assert result is True
    mock_setup.assert_called_once_with(app, registry=None)


# ── setup_studio_from_env: error handling ────────────────────────────────────

def test_setup_studio_from_env_import_error_is_caught(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ENABLE_STUDIO", "true")
    from ark_agentic.plugins.studio import setup_studio_from_env
    app = FastAPI()
    with patch("ark_agentic.plugins.studio.setup_studio", side_effect=ImportError("no module")):
        result = setup_studio_from_env(app)
    assert result is True


def test_setup_studio_from_env_generic_exception_is_caught(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ENABLE_STUDIO", "true")
    from ark_agentic.plugins.studio import setup_studio_from_env
    app = FastAPI()
    with patch("ark_agentic.plugins.studio.setup_studio", side_effect=RuntimeError("boom")):
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


def test_api_template_no_enable_studio_env_check_in_lifespan():
    """ENABLE_STUDIO 不应在 lifespan 内被读取——StudioPlugin 自己负责。"""
    rendered = _render_api_template()
    lifespan_start = rendered.index("async def lifespan")
    app_def_start = rendered.index("app = FastAPI(")
    lifespan_body = rendered[lifespan_start:app_def_start]
    assert "ENABLE_STUDIO" not in lifespan_body
    assert "setup_studio" not in lifespan_body


def test_api_template_uvicorn_entry_point():
    rendered = _render_api_template()
    assert '"test_proj.app:app"' in rendered


def test_api_template_studio_arrives_via_bootstrap_plugin_list():
    """模板里不应再手挂 setup_studio_from_env；Studio 通过 Bootstrap 的 plugin 列表接入。"""
    rendered = _render_api_template()
    assert "setup_studio_from_env" not in rendered
    assert "StudioPlugin()" in rendered
    assert "Bootstrap" in rendered


# ── CLI generates app.py + agent.json ────────────────────────────────────────

def test_cmd_init_default_creates_app_py_with_studio_via_bootstrap(tmp_path: Path):
    """默认 init 装配 server: app.py 通过 Bootstrap + plugin 列表接入 Studio。"""
    from ark_agentic.cli.main import _cmd_init
    args = type("Args", (), {"project_name": "myproj"})()
    with patch.object(Path, "cwd", return_value=tmp_path):
        _cmd_init(args)

    app_py = (tmp_path / "myproj" / "src" / "myproj" / "app.py").read_text(encoding="utf-8")
    assert "StudioPlugin()" in app_py
    assert "Bootstrap" in app_py
    # Auto-discovery via AgentsLifecycle replaces explicit registry seeding.
    assert "_bootstrap.agent_registry.register(" not in app_py
    # 旧的手挂方式不应再出现
    assert "setup_studio_from_env" not in app_py
    assert "include_router(chat_api.router)" not in app_py


def test_cmd_init_default_has_agent_json(tmp_path: Path):
    """init 默认创建 agent.json，供 Studio 发现。"""
    from ark_agentic.cli.main import _cmd_init
    args = type("Args", (), {"project_name": "myproj"})()
    with patch.object(Path, "cwd", return_value=tmp_path):
        _cmd_init(args)

    agent_json = (
        tmp_path
        / "myproj"
        / "src"
        / "myproj"
        / "agents"
        / "default"
        / "agent.json"
    )
    assert agent_json.is_file(), "agent.json must be created for Studio discovery"


# ── CLI add-agent generates agent.json ───────────────────────────────────────

def test_cmd_add_agent_generates_agent_json(tmp_path: Path):
    """add-agent must also generate agent.json for Studio discovery."""
    from ark_agentic.cli.main import _cmd_add_agent, _cmd_init

    init_args = type("Args", (), {"project_name": "myproj"})()
    with patch.object(Path, "cwd", return_value=tmp_path):
        _cmd_init(init_args)

    add_args = type("Args", (), {"agent_name": "billing"})()
    proj_root = tmp_path / "myproj"
    with patch.object(Path, "cwd", return_value=proj_root):
        _cmd_add_agent(add_args)

    agent_json = (
        proj_root
        / "src"
        / "myproj"
        / "agents"
        / "billing"
        / "agent.json"
    )
    assert agent_json.is_file(), "add-agent must generate agent.json"
    content = agent_json.read_text(encoding="utf-8")
    assert '"billing"' in content
