"""
Studio Tools API

读取 Agent 目录下的 tools/ 中的 Python 工具文件。
"""

from __future__ import annotations

import ast
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .agents import _agents_root

logger = logging.getLogger(__name__)

router = APIRouter()


class ToolMeta(BaseModel):
    name: str
    description: str = ""
    group: str = ""
    file_path: str = ""
    parameters: dict = Field(default_factory=dict)


class ToolListResponse(BaseModel):
    tools: list[ToolMeta]


def _parse_tool_file(tool_file: Path, agent_id: str) -> ToolMeta | None:
    """从 Python 文件中提取工具类信息（通过 AST 解析，不执行代码）。"""
    try:
        source = tool_file.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except Exception as e:
        logger.warning("Failed to parse %s: %s", tool_file, e)
        return None

    # 查找继承了 AgentTool 的类
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            # 检查类是否继承自 AgentTool
            is_tool = False
            for base in node.bases:
                if isinstance(base, ast.Name) and base.id == "AgentTool":
                    is_tool = True
                    break
            
            if not is_tool:
                continue

            # 检查是否有 name 属性赋值
            name = tool_file.stem
            description = ""
            group = ""
            parameters = {}

            # 读取 docstring
            if (node.body and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)):
                description = str(node.body[0].value.value).strip()

            # 读取类属性
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
                                # 解析 parameters = [ToolParameter(...), ...]
                                for elt in item.value.elts:
                                    if isinstance(elt, ast.Call) and isinstance(elt.func, ast.Name) and elt.func.id == "ToolParameter":
                                        param_dict = {}
                                        for kw in elt.keywords:
                                            if kw.arg is None:
                                                continue
                                            if isinstance(kw.value, ast.Constant):
                                                param_dict[kw.arg] = kw.value.value
                                            elif isinstance(kw.value, ast.List):
                                                # 处理 enum 等列表常量
                                                list_vals = []
                                                for le in kw.value.elts:
                                                    if isinstance(le, ast.Constant):
                                                        list_vals.append(le.value)
                                                param_dict[kw.arg] = list_vals
                                        
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


@router.get("/agents/{agent_id}/tools", response_model=ToolListResponse)
async def list_tools(agent_id: str):
    """列出 Agent 的所有 Tools (通过 AST 解析 Python 文件)。"""
    root = _agents_root()
    tools_dir = root / agent_id / "tools"
    if not tools_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")

    tools: list[ToolMeta] = []
    for py_file in sorted(tools_dir.glob("*.py")):
        if py_file.name.startswith("_"):
            continue
        meta = _parse_tool_file(py_file, agent_id)
        if meta:
            tools.append(meta)

    return ToolListResponse(tools=tools)
