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


# ── _render_env_sample (clean defaults) ──────────────────────────────────

def test_render_env_sample_is_clean_minimal():
    """env-sample 默认仅暴露 LLM 必填项 + 注释化的 server / 插件开关。"""
    out = _render_env_sample()
    # 必填项是“干净”的最小集
    assert "LLM_PROVIDER=openai" in out
    assert "MODEL_NAME=gpt-4o" in out
    assert "API_KEY=" in out
    # Plugin 开关是注释化的 opt-in，不在默认状态启用
    assert "# ENABLE_STUDIO=true" in out
    assert "# ENABLE_NOTIFICATIONS=true" in out
    assert "# ENABLE_JOB_MANAGER=true" in out


def test_render_env_sample_does_not_include_provider_specific_clutter():
    """干净默认意味着不再夹带 PA-SX / PA-JT / Phoenix / Langfuse 等历史变量。"""
    out = _render_env_sample()
    assert "PA-SX" not in out
    assert "PA-JT" not in out
    assert "PA_JT_" not in out
    assert "PHOENIX_COLLECTOR_ENDPOINT" not in out
    assert "LANGFUSE_" not in out
    assert "STUDIO_AUTH_TOKEN_SECRET" not in out


# ── Template content contract ────────────────────────────────────────────

def test_main_module_template_no_dead_imports():
    """MAIN_MODULE_TEMPLATE must not import create_chat_model, ToolRegistry, SessionManager, PromptConfig."""
    rendered = MAIN_MODULE_TEMPLATE.format(
        project_name="TestProj",
        package_name="test_proj",
        agent_name="default",
        agent_name_snake="default",
        agent_display_name="Default",
    )
    assert "create_chat_model" not in rendered
    assert "ToolRegistry" not in rendered
    assert "SessionManager" not in rendered
    assert "PromptConfig" not in rendered
    assert "create_default_agent" in rendered
    assert "load_dotenv" in rendered


def test_agent_module_template_uses_build_standard_agent():
    """AGENT_MODULE_TEMPLATE must use AgentDef + build_standard_agent (factory pattern), not manual wiring."""
    fmt = {
        "agent_name": "default",
        "agent_name_snake": "default",
        "agent_display_name": "Default",
    }
    rendered = AGENT_MODULE_TEMPLATE.format(**fmt)
    assert "AgentDef" in rendered
    assert "build_standard_agent" in rendered
    assert "from ark_agentic import AgentDef, AgentRunner, build_standard_agent" in rendered
    assert "_DEF = AgentDef(" in rendered
    assert "_AGENT_DIR" in rendered
    assert "skills_dir=_AGENT_DIR / \"skills\"" in rendered
    assert "from .tools import create_default_tools" in rendered
    # Must NOT contain old manual wiring
    assert "create_chat_model(" not in rendered
    assert "os.getenv(\"API_KEY\"" not in rendered
    assert "SkillConfig" not in rendered
    assert "SkillLoader" not in rendered
    assert "ToolRegistry()" not in rendered
    assert "SessionManager(" not in rendered
    assert "RunnerConfig(" not in rendered
    assert "PromptConfig(" not in rendered


def test_api_app_template_uses_bootstrap_default_plugins():
    """API_APP_TEMPLATE 应该体现 Bootstrap + DEFAULT_PLUGINS + AppContext 的装配方式，
    而不是手挂 chat_api / setup_studio_from_env。"""
    fmt = {
        "project_name": "TestProj",
        "package_name": "test_proj",
        "agent_name": "default",
        "agent_name_snake": "default",
        "agent_display_name": "Default",
    }
    rendered = API_APP_TEMPLATE.format(**fmt)

    # 新装配方式
    assert "from ark_agentic.bootstrap import DEFAULT_PLUGINS" in rendered
    assert "from ark_agentic.core.bootstrap import Bootstrap" in rendered
    assert "from ark_agentic.core.runtime.agents import AgentsRuntime" in rendered
    assert "from ark_agentic.plugins.api.context import AppContext" in rendered
    assert "AgentRegistry" in rendered
    assert "_registry.register(\"default\", create_default_agent())" in rendered
    assert "Bootstrap(_components)" in rendered
    assert "_bootstrap.install_routes(app)" in rendered
    assert "_bootstrap.start(ctx)" in rendered
    assert "_bootstrap.stop()" in rendered

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
    """init 默认装配 server: 必须生成 app.py + 默认 agent + .env-sample + agent.json。"""
    args = type("Args", (), {
        "project_name": "proj",
        "no_api": False,
    })()
    with patch.object(Path, "cwd", return_value=tmp_path):
        _cmd_init(args)
    root = tmp_path / "proj"
    assert root.is_dir()
    assert (root / "pyproject.toml").is_file()
    assert (root / ".env-sample").is_file()
    pkg = root / "src" / "proj"
    assert (pkg / "main.py").is_file()
    assert (pkg / "app.py").is_file(), "默认装配 server，应当生成 app.py"
    assert (pkg / "agents" / "default" / "agent.py").is_file()
    assert (pkg / "agents" / "default" / "agent.json").is_file(), "agent.json must always be generated"

    main_py = (pkg / "main.py").read_text(encoding="utf-8")
    assert "create_default_agent" in main_py

    agent_py = (pkg / "agents" / "default" / "agent.py").read_text(encoding="utf-8")
    assert "build_standard_agent" in agent_py
    assert "AgentDef" in agent_py

    tools_py = (pkg / "agents" / "default" / "tools" / "__init__.py").read_text(encoding="utf-8")
    assert "create_default_tools" in tools_py

    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    assert "ark-agentic[server]" in pyproject

    app_py = (pkg / "app.py").read_text(encoding="utf-8")
    assert "DEFAULT_PLUGINS" in app_py
    assert "Bootstrap" in app_py
    assert "AgentsRuntime(registry=_registry)" in app_py


def test_cmd_init_no_api_skips_app_py(tmp_path: Path):
    """--no-api 时不生成 app.py，只保留 main.py 适合 CLI 场景。"""
    args = type("Args", (), {
        "project_name": "proj",
        "no_api": True,
    })()
    with patch.object(Path, "cwd", return_value=tmp_path):
        _cmd_init(args)
    pkg = tmp_path / "proj" / "src" / "proj"
    assert (pkg / "main.py").is_file()
    assert not (pkg / "app.py").exists(), "--no-api 不应生成 app.py"


def test_cmd_init_when_dir_exists_exits_with_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    """init when project dir already exists prints error and exits 1."""
    (tmp_path / "existing").mkdir()
    args = type("Args", (), {
        "project_name": "existing",
        "no_api": False,
    })()
    with patch.object(Path, "cwd", return_value=tmp_path):
        with pytest.raises(SystemExit) as exc_info:
            _cmd_init(args)
        assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "已存在" in err or "existing" in err


# ── _cmd_add_agent ───────────────────────────────────────────────────────

def test_cmd_add_agent_creates_agent_files(tmp_path: Path):
    """add-agent 在已有项目里追加智能体目录骨架。"""
    init_args = type("Args", (), {
        "project_name": "proj",
        "no_api": False,
    })()
    with patch.object(Path, "cwd", return_value=tmp_path):
        _cmd_init(init_args)

    add_args = type("Args", (), {"agent_name": "weather"})()
    project_root = tmp_path / "proj"
    with patch.object(Path, "cwd", return_value=project_root):
        _cmd_add_agent(add_args)

    weather_dir = project_root / "src" / "proj" / "agents" / "weather"
    assert (weather_dir / "agent.py").is_file()
    assert (weather_dir / "agent.json").is_file()
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
