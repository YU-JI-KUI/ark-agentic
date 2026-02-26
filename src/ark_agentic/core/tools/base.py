"""
AgentTool 基类和辅助函数

参考: openclaw-main/src/agents/tools/common.ts
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal

from ..types import AgentToolResult, ToolCall


@dataclass
class ToolParameter:
    """工具参数定义"""

    name: str
    type: Literal["string", "integer", "number", "boolean", "array", "object"]
    description: str
    required: bool = True
    default: Any = None
    enum: list[Any] | None = None
    items: dict[str, Any] | None = None  # for array type
    properties: dict[str, Any] | None = None  # for object type

    def to_json_schema(self) -> dict[str, Any]:
        """转换为 JSON Schema 格式"""
        schema: dict[str, Any] = {
            "type": self.type,
            "description": self.description,
        }
        if self.enum:
            schema["enum"] = self.enum
        if self.items and self.type == "array":
            schema["items"] = self.items
        if self.properties and self.type == "object":
            schema["properties"] = self.properties
        if self.default is not None:
            schema["default"] = self.default
        return schema


class AgentTool(ABC):
    """工具基类

    所有工具需继承此类并实现 execute 方法。

    参考: openclaw-main/src/agents/tools/common.ts - AgentTool interface
    """

    # 工具基本信息（子类需覆盖）
    name: str = ""
    description: str = ""
    parameters: list[ToolParameter] = field(default_factory=list)

    # 工具分组（用于策略控制）
    group: str | None = None

    # 是否需要确认
    requires_confirmation: bool = False

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        # 确保子类定义了 name 和 description
        if not getattr(cls, "name", None):
            raise TypeError(f"Tool class {cls.__name__} must define 'name'")
        if not getattr(cls, "description", None):
            raise TypeError(f"Tool class {cls.__name__} must define 'description'")

    def get_json_schema(self) -> dict[str, Any]:
        """获取工具的 JSON Schema（用于 OpenAI function calling）"""
        properties = {}
        required = []

        for param in self.parameters:
            properties[param.name] = param.to_json_schema()
            if param.required:
                required.append(param.name)

        # OpenAI/DeepSeek 格式
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }

    @abstractmethod
    async def execute(
        self, tool_call: ToolCall, context: dict[str, Any] | None = None
    ) -> AgentToolResult:
        """执行工具

        Args:
            tool_call: 工具调用请求
            context: 执行上下文（可包含 session、user 等信息）

        Returns:
            工具执行结果
        """
        ...

    def to_langchain_tool(self, context: dict[str, Any] | None = None) -> Any:
        """适配为 LangChain StructuredTool（YAGNI：仅在需要接入 LangChain 生态时调用）。

        通过闭包绑定 context，解决 LangChain Tool 接口无法传递 context 的问题。

        Args:
            context: 执行上下文，闭包绑定后在每次工具调用时自动传入

        Returns:
            langchain_core.tools.StructuredTool 实例

        Raises:
            ImportError: 如果 langchain-core 未安装
        """
        try:
            from langchain_core.tools import StructuredTool
        except ImportError:
            raise ImportError(
                "langchain-core is required for to_langchain_tool(). "
                "Install with: uv add langchain-core"
            )

        tool_self = self
        bound_context = context

        async def _ainvoke(**kwargs: Any) -> str:
            """闭包：将 LangChain 调用转为 AgentTool.execute()"""
            import json

            tc = ToolCall(
                id=f"lc_{tool_self.name}",
                name=tool_self.name,
                arguments=kwargs,
            )
            result = await tool_self.execute(tc, context=bound_context)
            return result.output if result.output else json.dumps(
                result.to_dict() if hasattr(result, "to_dict") else str(result)
            )

        return StructuredTool.from_function(
            coroutine=_ainvoke,
            name=self.name,
            description=self.description,
            args_schema=None,  # 使用动态 kwargs
        )


# ============ 参数读取辅助函数 ============
# 参考: openclaw-main/src/agents/tools/common.ts - readStringParam etc.


def read_string_param(
    args: dict[str, Any], name: str, default: str | None = None
) -> str | None:
    """读取字符串参数"""
    value = args.get(name, default)
    if value is None:
        return default
    return str(value)


def read_string_param_required(args: dict[str, Any], name: str) -> str:
    """读取必需的字符串参数"""
    value = read_string_param(args, name)
    if value is None:
        raise ValueError(f"Missing required parameter: {name}")
    return value


def read_int_param(
    args: dict[str, Any], name: str, default: int | None = None
) -> int | None:
    """读取整数参数"""
    value = args.get(name, default)
    if value is None:
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def read_int_param_required(args: dict[str, Any], name: str) -> int:
    """读取必需的整数参数"""
    value = read_int_param(args, name)
    if value is None:
        raise ValueError(f"Missing required parameter: {name}")
    return value


def read_float_param(
    args: dict[str, Any], name: str, default: float | None = None
) -> float | None:
    """读取浮点数参数"""
    value = args.get(name, default)
    if value is None:
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def read_float_param_required(args: dict[str, Any], name: str) -> float:
    """读取必需的浮点数参数"""
    value = read_float_param(args, name)
    if value is None:
        raise ValueError(f"Missing required parameter: {name}")
    return value


def read_bool_param(
    args: dict[str, Any], name: str, default: bool | None = None
) -> bool | None:
    """读取布尔参数"""
    value = args.get(name, default)
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ("true", "1", "yes")
    return bool(value)


def read_bool_param_required(args: dict[str, Any], name: str) -> bool:
    """读取必需的布尔参数"""
    value = read_bool_param(args, name)
    if value is None:
        raise ValueError(f"Missing required parameter: {name}")
    return value


def read_list_param(
    args: dict[str, Any], name: str, default: list[Any] | None = None
) -> list[Any] | None:
    """读取列表参数"""
    value = args.get(name, default)
    if value is None:
        return default
    if isinstance(value, list):
        return value
    return default


def read_list_param_required(args: dict[str, Any], name: str) -> list[Any]:
    """读取必需的列表参数"""
    value = read_list_param(args, name)
    if value is None:
        raise ValueError(f"Missing required parameter: {name}")
    return value


def read_dict_param(
    args: dict[str, Any], name: str, default: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    """读取字典参数"""
    value = args.get(name, default)
    if value is None:
        return default
    if isinstance(value, dict):
        return value
    return default


def read_dict_param_required(args: dict[str, Any], name: str) -> dict[str, Any]:
    """读取必需的字典参数"""
    value = read_dict_param(args, name)
    if value is None:
        raise ValueError(f"Missing required parameter: {name}")
    return value
