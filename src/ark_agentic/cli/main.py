"""
ark-agentic CLI entry point.

Subcommands:
  init <project_name>       Scaffold a new agent project (默认含 server: API + Studio)
  add-agent <agent_name>    Add an agent module to an existing project
  version                   Print framework version
"""

from __future__ import annotations

import argparse
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


def _render_env_sample() -> str:
    """生成默认 .env-sample（保持干净的最小集）。"""
    return ENV_SAMPLE_TEMPLATE


# ── init ─────────────────────────────────────────────────────────────

def _cmd_init(args: argparse.Namespace) -> None:
    project_name: str = args.project_name
    package_name = _to_package_name(project_name)
    headless: bool = args.no_api

    root = Path.cwd() / project_name
    if root.exists():
        print(f"错误: 目录 '{project_name}' 已存在", file=sys.stderr)
        sys.exit(1)

    src = root / "src" / package_name
    default_agent = src / "agents" / "default"
    tests_dir = root / "tests"

    fmt = dict(
        project_name=project_name,
        package_name=package_name,
        agent_name="default",
        agent_name_snake="default",
        agent_display_name="Default",
    )

    _write(root / "pyproject.toml", PYPROJECT_TEMPLATE.format(**fmt))
    _write(root / "pip.conf", PIP_CONF_TEMPLATE)
    _write(root / ".env-sample", _render_env_sample())
    _write(src / "__init__.py", f'"""{project_name}"""\n')
    _write(src / "main.py", MAIN_MODULE_TEMPLATE.format(**fmt))
    _write(src / "agents" / "__init__.py", "")

    _write(default_agent / "__init__.py", AGENT_INIT_TEMPLATE.format(**fmt))
    _write(default_agent / "agent.py", AGENT_MODULE_TEMPLATE.format(**fmt))
    _write(default_agent / "tools" / "__init__.py", TOOL_TEMPLATE.format(**fmt))
    _touch(default_agent / "skills" / ".gitkeep")
    _write(default_agent / "agent.json", AGENT_JSON_TEMPLATE.format(**fmt))

    if not headless:
        _write(src / "app.py", API_APP_TEMPLATE.format(**fmt))
        static_dest = src / "static"
        static_dest.mkdir(parents=True, exist_ok=True)
        try:
            import ark_agentic as _ark
            ark_index = Path(_ark.__file__).parent / "static" / "index.html"
            if ark_index.is_file():
                shutil.copy(ark_index, static_dest / "index.html")
        except Exception:
            pass

    _write(tests_dir / "__init__.py", "")

    print(f"[OK] 项目 '{project_name}' 已创建")
    print()
    print("后续步骤:")
    print(f"  cd {project_name}")
    print("  uv pip install -e .")
    if headless:
        print(f"  python -m {package_name}.main")
    else:
        print(f"  uv run python -m {package_name}.app")
        print("  # 启用 Studio: 在 .env 中设置 ENABLE_STUDIO=true")
        print("  # 启用 Notifications + Jobs: ENABLE_NOTIFICATIONS=true / ENABLE_JOB_MANAGER=true")


# ── add-agent ────────────────────────────────────────────────────────

def _cmd_add_agent(args: argparse.Namespace) -> None:
    agent_name: str = args.agent_name
    agent_name_snake = _to_package_name(agent_name)
    agent_display_name = agent_name.replace("-", " ").replace("_", " ").title()

    pyproject = Path.cwd() / "pyproject.toml"
    if not pyproject.exists():
        print("错误: 当前目录未找到 pyproject.toml，请在项目根目录下运行", file=sys.stderr)
        sys.exit(1)

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
    _write(agents_dir / "agent.json", AGENT_JSON_TEMPLATE.format(**fmt))

    print(f"[OK] 智能体 '{agent_name}' 已添加到 src/{package_name}/agents/{agent_name_snake}/")
    print()
    print("后续步骤:")
    print(f"  1. 在 src/{package_name}/agents/{agent_name_snake}/tools/__init__.py 中实现 create_{agent_name_snake}_tools()")
    print("  2. 修改 _DEF 中的 agent_description，描述这个 agent 的职责")
    print(f"  3. 在 src/{package_name}/app.py 的 _registry 中追加注册：")
    print()
    print(f'       from .agents.{agent_name_snake} import create_{agent_name_snake}_agent')
    print(f'       _registry.register("{agent_name_snake}", create_{agent_name_snake}_agent())')


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
    p_init = sub.add_parser(
        "init",
        help="初始化新的智能体项目（默认装配 ark-agentic[server]: API + Studio）",
    )
    p_init.add_argument("project_name", help="项目名称")
    p_init.add_argument(
        "--no-api",
        action="store_true",
        help="生成纯 CLI 项目（不包含 app.py / Bootstrap 装配）",
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
