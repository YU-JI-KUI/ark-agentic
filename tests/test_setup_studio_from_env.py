"""
Acceptance tests for setup_studio_from_env() and STUDIO_APP_TEMPLATE changes.

Covers:
  - setup_studio_from_env: env=false skips, env=true delegates to setup_studio
  - setup_studio_from_env: ImportError and generic Exception are handled gracefully
  - STUDIO_APP_TEMPLATE: no ENABLE_STUDIO conditional in lifespan
  - STUDIO_APP_TEMPLATE: setup_studio_from_env called at module level
  - CLI --studio: generated app.py matches new contract
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest
from fastapi import FastAPI


# ── setup_studio_from_env: env gate ──────────────────────────────────────────

def test_setup_studio_from_env_disabled_by_default():
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
    assert result is True  # still returns True (env was set), but didn't crash


def test_setup_studio_from_env_generic_exception_is_caught(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ENABLE_STUDIO", "true")
    from ark_agentic.studio import setup_studio_from_env
    app = FastAPI()
    with patch("ark_agentic.studio.setup_studio", side_effect=RuntimeError("boom")):
        result = setup_studio_from_env(app)
    assert result is True  # still returns True, exception swallowed with logger.exception


# ── STUDIO_APP_TEMPLATE contract ─────────────────────────────────────────────

def _render_studio_template() -> str:
    from ark_agentic.cli.templates import STUDIO_APP_TEMPLATE
    return STUDIO_APP_TEMPLATE.format(
        project_name="TestProj",
        package_name="test_proj",
        agent_name="default",
        agent_name_snake="default",
        agent_display_name="Default",
    )


def test_studio_template_imports_setup_studio_from_env():
    rendered = _render_studio_template()
    assert "setup_studio_from_env" in rendered


def test_studio_template_calls_setup_studio_from_env_at_module_level():
    """setup_studio_from_env must be called outside the lifespan function."""
    rendered = _render_studio_template()
    lifespan_end = rendered.index("yield")
    studio_call_pos = rendered.index("setup_studio_from_env(app")
    assert studio_call_pos > lifespan_end, (
        "setup_studio_from_env should be called AFTER lifespan (at module level)"
    )


def test_studio_template_no_enable_studio_env_check_in_lifespan():
    """The lifespan must not contain ENABLE_STUDIO env-check — that's framework concern."""
    rendered = _render_studio_template()
    # Isolate lifespan body: between 'async def lifespan' and 'app = FastAPI('
    lifespan_start = rendered.index("async def lifespan")
    app_def_start = rendered.index("app = FastAPI(")
    lifespan_body = rendered[lifespan_start:app_def_start]
    assert "ENABLE_STUDIO" not in lifespan_body
    assert "setup_studio" not in lifespan_body


def test_studio_template_no_setup_studio_direct_import():
    """Template must use setup_studio_from_env, not the raw setup_studio."""
    rendered = _render_studio_template()
    # 'from ark_agentic.studio import setup_studio' must NOT appear (only from_env variant)
    assert "import setup_studio\n" not in rendered
    assert "from ark_agentic.studio import setup_studio_from_env" in rendered


# ── CLI --studio generates correct app.py ────────────────────────────────────

def test_cmd_init_with_studio_creates_app_py_using_setup_studio_from_env(tmp_path: Path):
    """init --studio generates app.py that uses setup_studio_from_env, not raw ENABLE_STUDIO check."""
    from ark_agentic.cli.main import _cmd_init
    args = type("Args", (), {
        "project_name": "myproj",
        "api": False,
        "studio": True,
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


def test_cmd_init_with_studio_app_py_has_agent_json(tmp_path: Path):
    """init --studio also creates agent.json for Studio discovery."""
    from ark_agentic.cli.main import _cmd_init
    args = type("Args", (), {
        "project_name": "myproj",
        "api": False,
        "studio": True,
        "memory": False,
        "llm_provider": "openai",
    })()
    with patch.object(Path, "cwd", return_value=tmp_path):
        _cmd_init(args)

    agent_json = tmp_path / "myproj" / "src" / "myproj" / "agents" / "default" / "agent.json"
    assert agent_json.is_file(), "agent.json must be created for Studio discovery"
