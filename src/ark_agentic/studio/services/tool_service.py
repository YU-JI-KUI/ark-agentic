from __future__ import annotations

"""
Tool Service — 纯业务逻辑

提供 Tool 的列表、解析和脚手架生成功能。
不依赖 FastAPI，可被 HTTP 端点和 Meta-Agent 工具共同调用。
"""

import ast
import logging
import re
from pathlib import Path

from ark_agentic.core.utils.env import resolve_agent_dir
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ── Models ──────────────────────────────────────────────────────────

class ToolMeta(BaseModel):
    name: str
    description: str = ""
    group: str = ""
    file_path: str = ""
    parameters: dict = Field(default_factory=dict)


class ToolParameterSpec(BaseModel):
    name: str
    description: str = ""
    type: str = "string"
    required: bool = True


# ── Public API ──────────────────────────────────────────────────────

def list_tools(agents_root: Path, agent_id: str) -> list[ToolMeta]:
    """列出 Agent 的所有 Tools (AST 解析)。"""
    agent_dir = resolve_agent_dir(agents_root, agent_id)
    if not agent_dir:
        raise FileNotFoundError(f"Agent not found: {agent_id}")
    tools_dir = agent_dir / "tools"
    if not tools_dir.is_dir():
        raise FileNotFoundError(f"Agent not found: {agent_id}")

    tools: list[ToolMeta] = []
    for py_file in sorted(tools_dir.glob("*.py")):
        if py_file.name.startswith("_"):
            continue
        meta = parse_tool_file(py_file, agent_id)
        if meta:
            tools.append(meta)
    return tools


def scaffold_tool(
    agents_root: Path,
    agent_id: str,
    name: str,
    description: str = "",
    parameters: list[dict] | None = None,
) -> ToolMeta:
    """生成 AgentTool Python 脚手架文件。

    Raises:
        ValueError: name 不合法 (非 Python 标识符)
        FileNotFoundError: Agent 不存在
        FileExistsError: 同名工具文件已存在
    """
    if not name or not name.isidentifier():
        raise ValueError(f"Tool name must be a valid Python identifier: {name}")

    agent_dir = resolve_agent_dir(agents_root, agent_id)
    if not agent_dir:
        raise FileNotFoundError(f"Agent not found: {agent_id}")
    tools_dir = agent_dir / "tools"
    if not tools_dir.is_dir():
        raise FileNotFoundError(f"Agent not found: {agent_id}")

    tool_file = tools_dir / f"{name}.py"
    if tool_file.exists():
        raise FileExistsError(f"Tool file already exists: {name}.py")

    # 渲染模板
    param_specs = [ToolParameterSpec(**p) for p in (parameters or [])]
    code = render_tool_template(name, description, param_specs)
    tool_file.write_text(code, encoding="utf-8")

    logger.info("Scaffolded tool: %s/%s", agent_id, name)

    # 解析刚生成的文件以返回标准 ToolMeta
    meta = parse_tool_file(tool_file, agent_id)
    return meta or ToolMeta(
        name=name, description=description,
        file_path=f"agents/{agent_id}/tools/{name}.py",
    )


def parse_tool_file(tool_file: Path, agent_id: str) -> ToolMeta | None:
    """通过 AST 解析 Python 文件，提取 AgentTool 子类的元数据。不执行代码。"""
    try:
        source = tool_file.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except Exception as e:
        logger.warning("Failed to parse %s: %s", tool_file, e)
        return None

    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue

        # 检查是否继承 AgentTool
        is_tool = any(
            isinstance(base, ast.Name) and base.id == "AgentTool"
            for base in node.bases
        )
        if not is_tool:
            continue

        name = tool_file.stem
        description = ""
        group = ""
        parameters: dict = {}

        # docstring
        if (node.body and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)):
            description = str(node.body[0].value.value).strip()

        # 类属性
        for item in node.body:
            if isinstance(item, ast.Assign):
                for target in item.targets:
                    if isinstance(target, ast.Name):
                        if target.id == "name" and isinstance(item.value, ast.Constant):
                            name = str(item.value.value)
                        elif target.id == "description" and isinstance(item.value, ast.Constant):
                            description = str(item.value.value)
                        elif target.id == "group" and isinstance(item.value, ast.Constant):
                            group = str(item.value.value)
                        elif target.id == "parameters" and isinstance(item.value, ast.List):
                            for elt in item.value.elts:
                                if isinstance(elt, ast.Call) and isinstance(elt.func, ast.Name) and elt.func.id == "ToolParameter":
                                    param_dict: dict = {}
                                    for kw in elt.keywords:
                                        if kw.arg is None:
                                            continue
                                        if isinstance(kw.value, ast.Constant):
                                            param_dict[kw.arg] = kw.value.value
                                        elif isinstance(kw.value, ast.List):
                                            param_dict[kw.arg] = [
                                                le.value for le in kw.value.elts
                                                if isinstance(le, ast.Constant)
                                            ]
                                    if "name" in param_dict:
                                        param_name = param_dict.pop("name")
                                        parameters[param_name] = param_dict

        return ToolMeta(
            name=name,
            description=description,
            group=group,
            file_path=f"agents/{agent_id}/tools/{tool_file.name}",
            parameters=parameters,
        )

    return None


# ── Template Rendering ──────────────────────────────────────────────

def render_tool_template(
    name: str,
    description: str,
    parameters: list[ToolParameterSpec] | None = None,
) -> str:
    """渲染 AgentTool Python 脚手架代码。"""
    class_name = _to_class_name(name)
    params = parameters or []

    param_lines = ""
    if params:
        param_entries = []
        for p in params:
            entry = f'        ToolParameter(name="{p.name}", description="{p.description}", type="{p.type}", required={p.required})'
            param_entries.append(entry)
        param_lines = "    parameters = [\n" + ",\n".join(param_entries) + ",\n    ]"
    else:
        param_lines = "    parameters = []"

    return f'''"""
{description or name}
"""

from __future__ import annotations

import logging
from typing import Any

from ark_agentic.core.tools.base import AgentTool, ToolParameter
from ark_agentic.core.types import AgentToolResult, ToolCall

logger = logging.getLogger(__name__)


class {class_name}(AgentTool):
    """{description or name}"""

    name = "{name}"
    description = "{description}"
{param_lines}

    async def execute(self, tool_call: ToolCall) -> AgentToolResult:
        # TODO: Implement tool logic
        return AgentToolResult(output="Not implemented yet")
'''


def _to_class_name(snake_name: str) -> str:
    """snake_case → PascalCase (e.g. my_tool → MyToolTool)."""
    parts = snake_name.split("_")
    pascal = "".join(p.capitalize() for p in parts)
    if not pascal.endswith("Tool"):
        pascal += "Tool"
    return pascal
