"""
Unit tests for ark-agentic CLI.

Covers: _to_package_name, _render_env_sample, template content contract,
_cmd_init, _cmd_add_agent, _cmd_version, and main() dispatch.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from ark_agentic.cli.main import (
    _cmd_add_agent,
    _cmd_init,
    _cmd_version,
    _render_env_sample,
    _to_package_name,
    main,
)
from ark_agentic.cli.templates import (
    AGENT_MODULE_TEMPLATE,
    API_APP_TEMPLATE,
    MAIN_MODULE_TEMPLATE,
    PYPROJECT_TEMPLATE,
)


# ── _to_package_name ─────────────────────────────────────────────────────

def test_to_package_name_replaces_hyphens():
    assert _to_package_name("my-project") == "my_project"


def test_to_package_name_preserves_underscores():
    assert _to_package_name("my_project") == "my_project"


def test_to_package_name_multiple_hyphens():
    assert _to_package_name("a-b-c") == "a_b_c"


# ── _render_env_sample ───────────────────────────────────────────────────

def test_render_env_sample_openai_contains_api_key_and_model():
    out = _render_env_sample("openai", "mypkg")
    assert "API_KEY=" in out
    assert "MODEL_NAME=" in out
    assert "LLM_PROVIDER=openai" in out
    assert "LLM_BASE_URL_IS_FULL_URL=false" in out
    assert "mypkg" in out or "AGENTS_ROOT" in out


def test_render_env_sample_pa_sx_contains_pa_vars():
    out = _render_env_sample("pa-sx", "mypkg")
    assert "LLM_PROVIDER=pa" in out
    assert "MODEL_NAME=PA-SX-80B" in out
    assert "API_KEY=" in out
    assert "LLM_BASE_URL=" in out


def test_render_env_sample_pa_jt_contains_pa_jt_vars():
    out = _render_env_sample("pa-jt", "mypkg")
    assert "LLM_PROVIDER=pa" in out
    assert "MODEL_NAME=PA-JT-80B" in out
    assert "PA_JT_" in out


def test_render_env_sample_empty_package_uses_placeholder():
    out = _render_env_sample("openai", "")
    assert "<package>" in out


# ── Template content contract (post CLI fix) ──────────────────────────────

def test_main_module_template_no_dead_imports():
    """MAIN_MODULE_TEMPLATE must not import create_chat_model, ToolRegistry, SessionManager, PromptConfig."""
    rendered = MAIN_MODULE_TEMPLATE.format(
        project_name="TestProj",
        package_name="test_proj",
        agent_name="default",
        agent_name_snake="default",
        agent_display_name="Default",
        api_deps="",
        ark_dep='"ark-agentic>=0.1.0",',
    )
    assert "create_chat_model" not in rendered
    assert "ToolRegistry" not in rendered
    assert "SessionManager" not in rendered
    assert "PromptConfig" not in rendered
    assert "create_default_agent" in rendered
    assert "load_dotenv" in rendered


def test_agent_module_template_uses_create_chat_model_from_env():
    """AGENT_MODULE_TEMPLATE must use create_chat_model_from_env(), not create_chat_model + API_KEY."""
    fmt = {
        "agent_name": "default",
        "agent_name_snake": "default",
        "agent_display_name": "Default",
    }
    rendered = AGENT_MODULE_TEMPLATE.format(**fmt)
    assert "create_chat_model_from_env" in rendered
    assert "create_chat_model(" not in rendered
    assert "os.getenv(\"API_KEY\"" not in rendered
    assert "SkillConfig" not in rendered
    assert "SkillLoader" not in rendered
    assert "_AGENT_DIR" not in rendered
    assert "_SKILLS_DIR" not in rendered


def test_api_app_template_uses_registry_and_router():
    """API_APP_TEMPLATE must use AgentRegistry + chat_api.router, no inline ChatRequest/ChatResponse."""
    fmt = {
        "project_name": "TestProj",
            "package_name": "test_proj",
            "agent_name": "default",
            "agent_name_snake": "default",
            "agent_display_name": "Default",
        }
    rendered = API_APP_TEMPLATE.format(**fmt)
    assert "AgentRegistry" in rendered
    assert "chat_api" in rendered
    assert "api_deps" in rendered
    assert "include_router(chat_api.router)" in rendered
    assert "init_registry" in rendered
    assert "class ChatRequest" not in rendered
    assert "class ChatResponse" not in rendered
    assert "class SSEEvent" not in rendered


def test_pyproject_template_placeholders():
    """PYPROJECT_TEMPLATE formats with expected keys."""
    fmt = {
        "project_name": "hello-world",
        "package_name": "hello_world",
        "agent_name": "default",
        "agent_name_snake": "default",
        "agent_display_name": "Default",
        "api_deps": "",
        "ark_dep": '"ark-agentic>=0.1.0",',
    }
    rendered = PYPROJECT_TEMPLATE.format(**fmt)
    assert "hello-world" in rendered
    assert "hello_world" in rendered
    assert "main:main_sync" in rendered


# ── _cmd_init ────────────────────────────────────────────────────────────

def test_cmd_init_creates_project_structure(tmp_path: Path):
    """init creates project dir, pyproject.toml, main.py, agent, .env-sample, agent.json."""
    args = type("Args", (), {
        "project_name": "proj",
        "api": False,
        "memory": False,
        "llm_provider": "openai",
    })()
    with patch.object(Path, "cwd", return_value=tmp_path):
        _cmd_init(args)
    root = tmp_path / "proj"
    assert root.is_dir()
    assert (root / "pyproject.toml").is_file()
    assert (root / ".env-sample").is_file()
    pkg = root / "src" / "proj"
    assert (pkg / "main.py").is_file()
    assert (pkg / "agents" / "default" / "agent.py").is_file()
    assert (pkg / "agents" / "default" / "agent.json").is_file(), "agent.json must always be generated"
    main_py = (pkg / "main.py").read_text(encoding="utf-8")
    assert "create_default_agent" in main_py
    agent_py = (pkg / "agents" / "default" / "agent.py").read_text(encoding="utf-8")
    assert "create_chat_model_from_env" in agent_py


def test_cmd_init_with_api_creates_app_py(tmp_path: Path):
    """init --api creates app.py with Studio support built-in."""
    args = type("Args", (), {
        "project_name": "proj",
        "api": True,
        "memory": False,
        "llm_provider": "openai",
    })()
    with patch.object(Path, "cwd", return_value=tmp_path):
        _cmd_init(args)
    app_py = (tmp_path / "proj" / "src" / "proj" / "app.py").read_text(encoding="utf-8")
    assert "AgentRegistry" in app_py
    assert "chat_api.router" in app_py
    assert "setup_studio_from_env" in app_py
    assert "class ChatRequest" not in app_py


def test_cmd_init_when_dir_exists_exits_with_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    """init when project dir already exists prints error and exits 1."""
    (tmp_path / "existing").mkdir()
    args = type("Args", (), {
        "project_name": "existing",
        "api": False,
        "memory": False,
        "llm_provider": "openai",
    })()
    with patch.object(Path, "cwd", return_value=tmp_path):
        with pytest.raises(SystemExit) as exc_info:
            _cmd_init(args)
        assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "已存在" in err or "existing" in err


# ── _cmd_version ─────────────────────────────────────────────────────────

def test_cmd_version_prints_version(capsys: pytest.CaptureFixture[str]):
    _cmd_version(type("Args", (), {})())
    out = capsys.readouterr().out
    assert "ark-agentic" in out


# ── main() dispatch ──────────────────────────────────────────────────────

def test_main_version_subcommand(capsys: pytest.CaptureFixture[str]):
    with patch.object(sys, "argv", ["ark-agentic", "version"]):
        main()
    out = capsys.readouterr().out
    assert "ark-agentic" in out


def test_main_unknown_subcommand_exits_non_zero(capsys: pytest.CaptureFixture[str]):
    """Unknown subcommand causes argparse to exit with non-zero (typically 2)."""
    with patch.object(sys, "argv", ["ark-agentic", "unknown"]):
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code != 0
    err = capsys.readouterr().err
    assert "invalid choice" in err or "ark-agentic" in err
