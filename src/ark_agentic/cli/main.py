"""
ark-agentic CLI entry point.

Subcommands:
  init <project_name>       Scaffold a new agent project (API + Studio, ready to run)
  add-agent <agent_name>    Add an agent module to an existing project
  version                   Print framework version
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ark_agentic import __version__

from .templates import (
    AGENT_INIT_TEMPLATE,
    AGENT_JSON_TEMPLATE,
    AGENT_MODULE_TEMPLATE,
    API_APP_TEMPLATE,
    ENV_SAMPLE_TEMPLATE,
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


# ── init ─────────────────────────────────────────────────────────────

def _cmd_init(args: argparse.Namespace) -> None:
    project_name: str = args.project_name
    package_name = _to_package_name(project_name)

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
        agent_class_name="DefaultAgent",
    )

    _write(root / "pyproject.toml", PYPROJECT_TEMPLATE.format(**fmt))
    _write(root / "pip.conf", PIP_CONF_TEMPLATE)
    _write(root / ".env-sample", ENV_SAMPLE_TEMPLATE)
    _write(root / ".env", ENV_SAMPLE_TEMPLATE)
    _write(src / "__init__.py", f'"""{project_name}"""\n')
    _write(src / "agents" / "__init__.py", "")

    _write(default_agent / "__init__.py", AGENT_INIT_TEMPLATE.format(**fmt))
    _write(default_agent / "agent.py", AGENT_MODULE_TEMPLATE.format(**fmt))
    _write(default_agent / "tools" / "__init__.py", TOOL_TEMPLATE.format(**fmt))
    _touch(default_agent / "skills" / ".gitkeep")
    _write(root / "data" / "ark_config" / "default" / "agent.json", AGENT_JSON_TEMPLATE.format(**fmt))

    _write(src / "app.py", API_APP_TEMPLATE.format(**fmt))

    # Copy UI assets from the framework's cli/_assets dir into the
    # project's static dir. Index.html reads window.ARK_AGENT_ID at
    # runtime — inject the default agent_id via a small inline script.
    static_dest = src / "static"
    static_dest.mkdir(parents=True, exist_ok=True)
    try:
        from ark_agentic.cli import _assets as _cli_assets
        assets_dir = Path(_cli_assets.__file__).parent
        for asset_name in ("index.html", "a2ui-renderer.js"):
            src_asset = assets_dir / asset_name
            if not src_asset.is_file():
                continue
            content = src_asset.read_text(encoding="utf-8")
            if asset_name == "index.html":
                agent_script = (
                    '<head>\n  <script>'
                    'window.ARK_AGENT_ID = "default";'
                    '</script>'
                )
                content = content.replace("<head>", agent_script, 1)
            (static_dest / asset_name).write_text(content, encoding="utf-8")
    except Exception:
        pass

    _write(tests_dir / "__init__.py", "")

    print(f"[OK] 项目 '{project_name}' 已创建")
    print()
    print("后续步骤:")
    print(f"  cd {project_name}")
    print("  uv pip install -e .")
    print(f"  uv run {project_name}")


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

    agent_class_name = (
        "".join(w.capitalize() for w in agent_name_snake.split("_")) + "Agent"
    )
    fmt = dict(
        agent_name=agent_name,
        agent_name_snake=agent_name_snake,
        agent_display_name=agent_display_name,
        agent_class_name=agent_class_name,
    )

    _write(agents_dir / "__init__.py", AGENT_INIT_TEMPLATE.format(**fmt))
    _write(agents_dir / "agent.py", AGENT_MODULE_TEMPLATE.format(**fmt))
    _write(agents_dir / "tools" / "__init__.py", TOOL_TEMPLATE.format(**fmt))
    _touch(agents_dir / "skills" / ".gitkeep")
    _write(
        Path.cwd() / "data" / "ark_config" / agent_name_snake / "agent.json",
        AGENT_JSON_TEMPLATE.format(**fmt),
    )

    print(f"[OK] 智能体 '{agent_name}' 已添加到 src/{package_name}/agents/{agent_name_snake}/")
    print()
    print("后续步骤:")
    print(f"  1. 在 src/{package_name}/agents/{agent_name_snake}/tools/__init__.py 中实现 create_{agent_name_snake}_tools()")
    print(f"  2. 在 src/{package_name}/agents/{agent_name_snake}/agent.py 中修改 agent_description，描述这个 agent 的职责")
    print("  3. 框架启动时自动扫描并注册 BaseAgent 子类，无需手动注册")


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
        help="初始化新的智能体项目（API + Studio，开箱即跑）",
    )
    p_init.add_argument("project_name", help="项目名称")

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
