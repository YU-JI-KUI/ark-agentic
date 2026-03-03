"""
ark-agentic CLI entry point.

Subcommands:
  init <project_name>       Scaffold a new agent project
  add-agent <agent_name>    Add an agent module to an existing project
  version                   Print framework version
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

from ark_agentic import __version__

from .templates import (
    AGENT_INIT_TEMPLATE,
    AGENT_JSON_TEMPLATE,
    AGENT_MODULE_TEMPLATE,
    API_APP_TEMPLATE,
    ENV_SAMPLE_TEMPLATE,
    MAIN_MODULE_TEMPLATE,
    PIP_CONF_TEMPLATE,
    PYPROJECT_TEMPLATE,
    STUDIO_APP_TEMPLATE,
    TOOL_TEMPLATE,
)


def _to_package_name(project_name: str) -> str:
    return project_name.replace("-", "_")


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()


def _render_env_sample(llm_provider: str, package_name: str = "") -> str:
    """根据选择的 LLM 提供商生成 .env-sample 内容。"""
    if llm_provider == "pa-sx":
        provider_block = "\n".join(
            [
                "LLM_PROVIDER=pa",
                "PA_MODEL=PA-SX-80B",
                "PA_SX_BASE_URL=https://pa-sx.example.com",
            ]
        )
    elif llm_provider == "pa-jt":
        provider_block = "\n".join(
            [
                "LLM_PROVIDER=pa",
                "PA_MODEL=PA-JT-80B",
                "PA_JT_BASE_URL=https://pa-jt.example.com",
            ]
        )
    elif llm_provider == "openai":
        provider_block = "\n".join(
            [
                "LLM_PROVIDER=openai",
                "DEEPSEEK_API_KEY=sk-xxx",
                "# LLM_BASE_URL=https://api.openai.com/v1",
            ]
        )
    else:  # deepseek (default)
        provider_block = "\n".join(
            [
                "LLM_PROVIDER=deepseek",
                "DEEPSEEK_API_KEY=sk-xxx",
                "# LLM_BASE_URL=https://api.deepseek.com",
            ]
        )

    return ENV_SAMPLE_TEMPLATE.format(provider_block=provider_block, package_name=package_name or "<package>")


# ── init ─────────────────────────────────────────────────────────────

def _cmd_init(args: argparse.Namespace) -> None:
    project_name: str = args.project_name
    package_name = _to_package_name(project_name)
    include_api: bool = args.api or args.studio  # --studio implies --api
    include_studio: bool = args.studio
    include_memory: bool = args.memory
    llm_provider: str = args.llm_provider

    root = Path.cwd() / project_name
    if root.exists():
        print(f"错误: 目录 '{project_name}' 已存在", file=sys.stderr)
        sys.exit(1)

    src = root / "src" / package_name
    default_agent = src / "agents" / "default"
    tests_dir = root / "tests"

    api_deps = (
        '\n    "fastapi>=0.110.0",\n    "uvicorn[standard]>=0.29.0",'
        if include_api else ""
    )

    ark_dep = '"ark-agentic[memory]>=0.1.0",' if include_memory else '"ark-agentic>=0.1.0",'

    fmt = dict(
        project_name=project_name,
        package_name=package_name,
        agent_name="default",
        agent_name_snake="default",
        agent_display_name="Default",
        api_deps=api_deps,
        ark_dep=ark_dep,
    )

    # pyproject.toml
    _write(root / "pyproject.toml", PYPROJECT_TEMPLATE.format(**fmt))

    # pip.conf
    _write(root / "pip.conf", PIP_CONF_TEMPLATE)

    # .env-sample
    _write(root / ".env-sample", _render_env_sample(llm_provider, package_name))

    # src/<pkg>/__init__.py
    _write(src / "__init__.py", f'"""{project_name}"""\n')

    # src/<pkg>/main.py
    _write(src / "main.py", MAIN_MODULE_TEMPLATE.format(**fmt))

    # src/<pkg>/agents/__init__.py
    _write(src / "agents" / "__init__.py", "")

    # default agent
    _write(default_agent / "__init__.py", AGENT_INIT_TEMPLATE.format(**fmt))
    _write(default_agent / "agent.py", AGENT_MODULE_TEMPLATE.format(**fmt))
    _write(default_agent / "tools" / "__init__.py", TOOL_TEMPLATE.format(**fmt))
    _touch(default_agent / "skills" / ".gitkeep")

    # optional: API server
    if include_api:
        if include_studio:
            # Studio-aware app: uses ark-agentic registry pattern from app.py
            _write(src / "app.py", STUDIO_APP_TEMPLATE.format(**fmt))
        else:
            _write(src / "api.py", API_APP_TEMPLATE.format(**fmt))
        static_dest = src / "static"
        static_dest.mkdir(parents=True, exist_ok=True)
        try:
            import ark_agentic as _ark
            ark_index = Path(_ark.__file__).parent / "static" / "index.html"
            if ark_index.is_file():
                shutil.copy(ark_index, static_dest / "index.html")
        except Exception:
            pass

    # agent.json for Studio discovery
    if include_studio:
        _write(default_agent / "agent.json", AGENT_JSON_TEMPLATE.format(**fmt))

    # tests
    _write(tests_dir / "__init__.py", "")

    print(f"✅ 项目 '{project_name}' 已创建")
    if include_studio:
        print()
        print("📦 Studio 模式已启用:")
        print(f"   app.py 生成: src/{package_name}/app.py")
        print(f"   agent.json 生成: src/{package_name}/agents/default/agent.json")
        print()
    print()
    print("后续步骤:")
    print(f"  cd {project_name}")
    print("  uv pip install -e '.[server]'")
    if include_studio:
        print(f"  设置环境变量: ENABLE_STUDIO=true 和 AGENTS_ROOT=./src/{package_name}/agents")
        print(f"  uv run python -m {package_name}.app")
        print("  访问 http://localhost:8080/studio 查看控制台")
    else:
        print(f"  python -m {package_name}.main")


# ── add-agent ────────────────────────────────────────────────────────

def _cmd_add_agent(args: argparse.Namespace) -> None:
    agent_name: str = args.agent_name
    agent_name_snake = _to_package_name(agent_name)
    agent_display_name = agent_name.replace("-", " ").replace("_", " ").title()

    pyproject = Path.cwd() / "pyproject.toml"
    if not pyproject.exists():
        print("错误: 当前目录未找到 pyproject.toml，请在项目根目录下运行", file=sys.stderr)
        sys.exit(1)

    # Detect package name from src/ structure
    src_dir = Path.cwd() / "src"
    if not src_dir.is_dir():
        print("错误: 未找到 src/ 目录", file=sys.stderr)
        sys.exit(1)

    packages = [
        d.name for d in src_dir.iterdir()
        if d.is_dir() and (d / "__init__.py").exists()
    ]
    if not packages:
        print("错误: src/ 下未找到 Python 包", file=sys.stderr)
        sys.exit(1)

    package_name = packages[0]
    agents_dir = src_dir / package_name / "agents" / agent_name_snake

    if agents_dir.exists():
        print(f"错误: 智能体 '{agent_name}' 已存在", file=sys.stderr)
        sys.exit(1)

    fmt = dict(
        agent_name=agent_name,
        agent_name_snake=agent_name_snake,
        agent_display_name=agent_display_name,
    )

    _write(agents_dir / "__init__.py", AGENT_INIT_TEMPLATE.format(**fmt))
    _write(agents_dir / "agent.py", AGENT_MODULE_TEMPLATE.format(**fmt))
    _write(agents_dir / "tools" / "__init__.py", TOOL_TEMPLATE.format(**fmt))
    _touch(agents_dir / "skills" / ".gitkeep")

    print(f"✅ 智能体 '{agent_name}' 已添加到 src/{package_name}/agents/{agent_name_snake}/")


# ── version ──────────────────────────────────────────────────────────

def _cmd_version(_args: argparse.Namespace) -> None:
    print(f"ark-agentic {__version__}")


# ── entry point ──────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="ark-agentic",
        description="ark-agentic 脚手架工具",
    )
    sub = parser.add_subparsers(dest="command")

    # init
    p_init = sub.add_parser("init", help="初始化新的智能体项目")
    p_init.add_argument("project_name", help="项目名称")
    p_init.add_argument("--api", action="store_true", help="包含 FastAPI 服务模板")
    p_init.add_argument("--studio", action="store_true", help="包含 Ark-Agentic Studio 管控台（自动启用 --api）")
    p_init.add_argument("--memory", action="store_true", help="包含记忆系统配置")
    p_init.add_argument(
        "--llm-provider",
        default="deepseek",
        choices=["deepseek", "openai", "pa-sx", "pa-jt"],
        help="默认 LLM 提供商 (default: deepseek)",
    )

    # add-agent
    p_add = sub.add_parser("add-agent", help="向现有项目添加新智能体")
    p_add.add_argument("agent_name", help="智能体名称")

    # version
    sub.add_parser("version", help="显示版本号")

    args = parser.parse_args()

    handlers = {
        "init": _cmd_init,
        "add-agent": _cmd_add_agent,
        "version": _cmd_version,
    }

    handler = handlers.get(args.command)
    if handler is None:
        parser.print_help()
        sys.exit(1)

    handler(args)


if __name__ == "__main__":
    main()
