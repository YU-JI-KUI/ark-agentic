"""
Unit tests for ark-agentic CLI.

Covers: _to_package_name, ENV_SAMPLE_TEMPLATE, template content contract,
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
    _to_package_name,
    main,
)
from ark_agentic.cli.templates import (
    AGENT_MODULE_TEMPLATE,
    API_APP_TEMPLATE,
    ENV_SAMPLE_TEMPLATE,
    PYPROJECT_TEMPLATE,
)


# ── _to_package_name ─────────────────────────────────────────────────────

def test_to_package_name_replaces_hyphens():
    assert _to_package_name("my-project") == "my_project"


def test_to_package_name_preserves_underscores():
    assert _to_package_name("my_project") == "my_project"


def test_to_package_name_multiple_hyphens():
    assert _to_package_name("a-b-c") == "a_b_c"


# ── ENV_SAMPLE_TEMPLATE (Studio on by default) ───────────────────────────

def test_env_sample_studio_enabled_by_default():
    """ENABLE_STUDIO 默认就是开的 —— init 之后开箱即跑 API+Studio。"""
    out = ENV_SAMPLE_TEMPLATE
    assert "LLM_PROVIDER=openai" in out
    assert "MODEL_NAME=gpt-4o" in out
    assert "API_KEY=" in out
    # Studio 默认开（未注释）
    assert "\nENABLE_STUDIO=true" in out
    # 其它插件仍是 opt-in
    assert "# ENABLE_NOTIFICATIONS=true" in out
    assert "# ENABLE_JOB_MANAGER=true" in out


def test_env_sample_does_not_include_provider_specific_clutter():
    """干净默认意味着不再夹带 PA-SX / PA-JT / Phoenix / Langfuse 等历史变量。"""
    out = ENV_SAMPLE_TEMPLATE
    assert "PA-SX" not in out
    assert "PA-JT" not in out
    assert "PA_JT_" not in out
    assert "PHOENIX_COLLECTOR_ENDPOINT" not in out
    assert "LANGFUSE_" not in out
    assert "STUDIO_AUTH_TOKEN_SECRET" not in out


# ── Template content contract ────────────────────────────────────────────

def test_agent_module_template_subclasses_base_agent():
    """AGENT_MODULE_TEMPLATE must declare a ``BaseAgent`` subclass — no
    factory function, no AgentDef, no manual wiring."""
    fmt = {
        "agent_name": "default",
        "agent_name_snake": "default",
        "agent_display_name": "Default",
        "agent_class_name": "DefaultAgent",
    }
    rendered = AGENT_MODULE_TEMPLATE.format(**fmt)
    assert "from ark_agentic import BaseAgent" in rendered
    assert "class DefaultAgent(BaseAgent):" in rendered
    assert 'agent_id = "default"' in rendered
    assert 'agent_name = "Default"' in rendered
    assert "def build_tools(self):" in rendered
    assert "from .tools import create_default_tools" in rendered
    # Old factory pattern must be gone
    assert "AgentDef" not in rendered
    assert "build_standard_agent" not in rendered
    assert "_DEF = " not in rendered
    assert "create_chat_model(" not in rendered
    assert "SkillConfig" not in rendered
    assert "SkillLoader" not in rendered
    assert "ToolRegistry()" not in rendered
    assert "SessionManager(" not in rendered
    assert "RunnerConfig(" not in rendered
    assert "PromptConfig(" not in rendered


def test_api_app_template_uses_bootstrap_with_auto_discovery():
    """API_APP_TEMPLATE 装配 Bootstrap + AppContext，agent 由自动扫描发现，
    不再手动 register。挂 ``/`` 与 ``/api/static`` 用项目自带的 static 目录。"""
    fmt = {
        "project_name": "TestProj",
        "package_name": "test_proj",
        "agent_name": "default",
        "agent_name_snake": "default",
        "agent_display_name": "Default",
        "agent_class_name": "DefaultAgent",
    }
    rendered = API_APP_TEMPLATE.format(**fmt)

    # 新装配方式
    assert "from ark_agentic.core.protocol.bootstrap import Bootstrap" in rendered
    assert "from ark_agentic.core.protocol.app_context import AppContext" in rendered
    assert "_bootstrap.install_routes(app)" in rendered
    assert "_bootstrap.start(ctx)" in rendered
    assert "_bootstrap.stop()" in rendered

    # UI mount points (project bundles its own static)
    assert "/api/static" in rendered
    assert "StaticFiles" in rendered
    assert "/studio" in rendered  # studio playground redirect

    # 自动扫描代替手动注册
    assert "_bootstrap.agent_registry.register(" not in rendered
    assert "create_default_agent" not in rendered

    # 旧的手挂 / 内联模型不应再出现
    assert "setup_studio_from_env" not in rendered
    assert "include_router(chat_api.router)" not in rendered
    assert "init_registry" not in rendered
    assert "class ChatRequest" not in rendered
    assert "class ChatResponse" not in rendered
    assert "class SSEEvent" not in rendered


def test_pyproject_template_pins_server_extra():
    """PYPROJECT_TEMPLATE 默认依赖 ark-agentic[server]，而不是裸的 ark-agentic + 可选 fastapi/uvicorn 行。"""
    fmt = {
        "project_name": "hello-world",
        "package_name": "hello_world",
        "agent_name": "default",
        "agent_name_snake": "default",
        "agent_display_name": "Default",
    }
    rendered = PYPROJECT_TEMPLATE.format(**fmt)
    assert "hello-world" in rendered
    assert "hello_world" in rendered
    assert '"ark-agentic[server]>=0.5.0"' in rendered
    # 旧模板里把 fastapi/uvicorn 单独追加到依赖列表的写法不再需要
    assert "fastapi>=" not in rendered
    assert "uvicorn[standard]" not in rendered
    # 入口指向 app:main（带 server 的项目以 HTTP 入口为主）
    assert "app:main" in rendered


# ── _cmd_init ────────────────────────────────────────────────────────────

def test_cmd_init_creates_project_structure(tmp_path: Path):
    """init 装配 API + Studio: 生成 app.py + 默认 agent + CONFIG_DIR 元数据。"""
    args = type("Args", (), {"project_name": "proj"})()
    with patch.object(Path, "cwd", return_value=tmp_path):
        _cmd_init(args)
    root = tmp_path / "proj"
    assert root.is_dir()
    assert (root / "pyproject.toml").is_file()
    assert (root / ".env-sample").is_file()
    assert (root / ".env").is_file(), ".env 必须直接生成，开箱即跑"
    pkg = root / "src" / "proj"
    assert not (pkg / "main.py").exists(), "默认入口是 app.py，不再生成 main.py"
    assert (pkg / "app.py").is_file(), "默认装配 server，应当生成 app.py"
    assert (pkg / "agents" / "default" / "agent.py").is_file()
    assert (root / "data" / "ark_config" / "default" / "agent.json").is_file()

    agent_py = (pkg / "agents" / "default" / "agent.py").read_text(encoding="utf-8")
    assert "class DefaultAgent(BaseAgent):" in agent_py
    assert 'agent_id = "default"' in agent_py

    tools_py = (pkg / "agents" / "default" / "tools" / "__init__.py").read_text(encoding="utf-8")
    assert "create_default_tools" in tools_py

    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    assert "ark-agentic[server]" in pyproject

    app_py = (pkg / "app.py").read_text(encoding="utf-8")
    assert "Bootstrap" in app_py
    # No manual register call — auto-discovery scans agents/ at start()
    assert "_bootstrap.agent_registry.register(" not in app_py

    # UI assets bundled into the project so users can edit them
    static_dir = pkg / "static"
    assert (static_dir / "index.html").is_file()
    assert (static_dir / "a2ui-renderer.js").is_file()
    index_html = (static_dir / "index.html").read_text(encoding="utf-8")
    # Default agent_id is injected so the bundled chat-demo just works
    assert 'window.ARK_AGENT_ID = "default"' in index_html


def test_cmd_init_when_dir_exists_exits_with_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    """init when project dir already exists prints error and exits 1."""
    (tmp_path / "existing").mkdir()
    args = type("Args", (), {"project_name": "existing"})()
    with patch.object(Path, "cwd", return_value=tmp_path):
        with pytest.raises(SystemExit) as exc_info:
            _cmd_init(args)
        assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "已存在" in err or "existing" in err


# ── _cmd_add_agent ───────────────────────────────────────────────────────

def test_cmd_add_agent_creates_agent_files(tmp_path: Path):
    """add-agent 在已有项目里追加智能体目录骨架。"""
    init_args = type("Args", (), {"project_name": "proj"})()
    with patch.object(Path, "cwd", return_value=tmp_path):
        _cmd_init(init_args)

    add_args = type("Args", (), {"agent_name": "weather"})()
    project_root = tmp_path / "proj"
    with patch.object(Path, "cwd", return_value=project_root):
        _cmd_add_agent(add_args)

    weather_dir = project_root / "src" / "proj" / "agents" / "weather"
    assert (weather_dir / "agent.py").is_file()
    assert (project_root / "data" / "ark_config" / "weather" / "agent.json").is_file()
    assert (weather_dir / "tools" / "__init__.py").is_file()


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
