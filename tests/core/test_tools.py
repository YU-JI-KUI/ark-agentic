"""Tests for agent tools."""

import pytest
from ark_agentic.core.tools.base import (
    AgentTool,
    ToolParameter,
    read_bool_param,
    read_dict_param,
    read_float_param,
    read_int_param,
    read_list_param,
    read_string_param,
    read_string_param_required,
)
from ark_agentic.core.tools.registry import ToolRegistry
from ark_agentic.core.types import AgentToolResult, ToolCall


class TestToolParameter:
    """Tests for ToolParameter."""

    def test_basic_parameter(self) -> None:
        """Test basic parameter creation."""
        param = ToolParameter(
            name="query",
            type="string",
            description="Search query"
        )
        assert param.name == "query"
        assert param.type == "string"
        assert param.required

    def test_to_json_schema_basic(self) -> None:
        """Test basic JSON schema conversion."""
        param = ToolParameter(
            name="query",
            type="string",
            description="Search query"
        )
        schema = param.to_json_schema()
        assert schema["type"] == "string"
        assert schema["description"] == "Search query"

    def test_to_json_schema_with_enum(self) -> None:
        """Test JSON schema with enum."""
        param = ToolParameter(
            name="status",
            type="string",
            description="Status",
            enum=["active", "inactive"]
        )
        schema = param.to_json_schema()
        assert schema["enum"] == ["active", "inactive"]

    def test_to_json_schema_with_default(self) -> None:
        """Test JSON schema with default."""
        param = ToolParameter(
            name="count",
            type="integer",
            description="Count",
            default=10
        )
        schema = param.to_json_schema()
        assert schema["default"] == 10


class TestAgentTool:
    """Tests for AgentTool base class."""

    def test_subclass_requires_name(self) -> None:
        """Test that subclass must define name."""
        with pytest.raises(TypeError):
            class BadTool(AgentTool):
                description = "Test"

                async def execute(self, tool_call, context=None):
                    pass

    def test_subclass_requires_description(self) -> None:
        """Test that subclass must define description."""
        with pytest.raises(TypeError):
            class BadTool(AgentTool):
                name = "test"

                async def execute(self, tool_call, context=None):
                    pass

    def test_valid_subclass(self) -> None:
        """Test valid tool subclass."""
        class TestTool(AgentTool):
            name = "test_tool"
            description = "A test tool"
            parameters = [
                ToolParameter(
                    name="input",
                    type="string",
                    description="Input value"
                )
            ]

            async def execute(self, tool_call, context=None):
                return AgentToolResult.text_result(tool_call.id, "done")

        tool = TestTool()
        assert tool.name == "test_tool"
        assert tool.description == "A test tool"

    def test_get_json_schema(self) -> None:
        """Test JSON schema generation."""
        class TestTool(AgentTool):
            name = "test_tool"
            description = "A test tool"
            parameters = [
                ToolParameter(
                    name="query",
                    type="string",
                    description="Query string",
                    required=True
                ),
                ToolParameter(
                    name="limit",
                    type="integer",
                    description="Result limit",
                    required=False
                )
            ]

            async def execute(self, tool_call, context=None):
                return AgentToolResult.text_result(tool_call.id, "done")

        tool = TestTool()
        schema = tool.get_json_schema()

        # OpenAI-compatible format
        assert schema["type"] == "function"
        assert "function" in schema
        func = schema["function"]
        assert func["name"] == "test_tool"
        assert func["description"] == "A test tool"
        assert "parameters" in func
        assert func["parameters"]["type"] == "object"
        assert "query" in func["parameters"]["properties"]
        assert "query" in func["parameters"]["required"]
        assert "limit" not in func["parameters"]["required"]


class TestToolRegistry:
    """Tests for ToolRegistry."""

    def _create_test_tool(self, tool_name: str) -> AgentTool:
        """Create a test tool dynamically."""
        # 使用 type() 动态创建类来避�?__init_subclass__ 检�?
        async def execute(self, tool_call, context=None):
            return AgentToolResult.text_result(tool_call.id, "done")

        tool_class = type(
            f"TestTool_{tool_name}",
            (AgentTool,),
            {
                "name": tool_name,
                "description": f"Tool {tool_name}",
                "parameters": [],
                "execute": execute,
            }
        )
        return tool_class()

    def test_register(self) -> None:
        """Test tool registration."""
        registry = ToolRegistry()
        tool = self._create_test_tool("test1")
        registry.register(tool)
        assert registry.get("test1") == tool

    def test_register_duplicate(self) -> None:
        """Test duplicate registration raises error."""
        registry = ToolRegistry()
        tool = self._create_test_tool("test1")
        registry.register(tool)
        with pytest.raises(ValueError):
            registry.register(tool)

    def test_register_all(self) -> None:
        """Test bulk registration."""
        registry = ToolRegistry()
        tools = [
            self._create_test_tool("test1"),
            self._create_test_tool("test2"),
        ]
        registry.register_all(tools)
        assert len(registry.list_all()) == 2

    def test_unregister(self) -> None:
        """Test tool unregistration."""
        registry = ToolRegistry()
        tool = self._create_test_tool("test1")
        registry.register(tool)
        assert registry.unregister("test1")
        assert registry.get("test1") is None

    def test_get_not_found(self) -> None:
        """Test getting non-existent tool."""
        registry = ToolRegistry()
        assert registry.get("nonexistent") is None

    def test_list_all(self) -> None:
        """Test listing all tools."""
        registry = ToolRegistry()
        registry.register(self._create_test_tool("test1"))
        registry.register(self._create_test_tool("test2"))
        tools = registry.list_all()
        assert len(tools) == 2
        names = [t.name for t in tools]
        assert "test1" in names
        assert "test2" in names

    def test_list_names(self) -> None:
        """Test listing tool names."""
        registry = ToolRegistry()
        registry.register(self._create_test_tool("test1"))
        registry.register(self._create_test_tool("test2"))
        names = registry.list_names()
        assert set(names) == {"test1", "test2"}

    def test_get_schemas(self) -> None:
        """Test getting JSON schemas."""
        registry = ToolRegistry()
        registry.register(self._create_test_tool("test1"))
        schemas = registry.get_schemas()
        assert len(schemas) == 1
        # OpenAI-compatible format
        assert schemas[0]["type"] == "function"
        assert schemas[0]["function"]["name"] == "test1"

    def test_clear(self) -> None:
        """Test clearing registry."""
        registry = ToolRegistry()
        registry.register(self._create_test_tool("test1"))
        registry.clear()
        assert len(registry.list_all()) == 0


class TestParameterReaders:
    """Tests for parameter reading functions."""

    def test_read_string_param(self) -> None:
        """Test string parameter reading."""
        args = {"name": "value"}
        assert read_string_param(args, "name") == "value"
        assert read_string_param(args, "missing") is None
        assert read_string_param(args, "missing", "default") == "default"

    def test_read_string_param_required(self) -> None:
        """Test required string parameter."""
        args = {"name": "value"}
        assert read_string_param_required(args, "name") == "value"
        with pytest.raises(ValueError):
            read_string_param_required(args, "missing")

    def test_read_int_param(self) -> None:
        """Test integer parameter reading."""
        args = {"count": 42, "text": "123"}
        assert read_int_param(args, "count") == 42
        assert read_int_param(args, "text") == 123
        assert read_int_param(args, "missing") is None
        assert read_int_param(args, "missing", 0) == 0

    def test_read_float_param(self) -> None:
        """Test float parameter reading."""
        args = {"score": 3.14, "text": "2.5"}
        assert read_float_param(args, "score") == 3.14
        assert read_float_param(args, "text") == 2.5
        assert read_float_param(args, "missing") is None

    def test_read_bool_param(self) -> None:
        """Test boolean parameter reading."""
        args = {
            "flag1": True,
            "flag2": "true",
            "flag3": "yes",
            "flag4": False
        }
        assert read_bool_param(args, "flag1") is True
        assert read_bool_param(args, "flag2") is True
        assert read_bool_param(args, "flag3") is True
        assert read_bool_param(args, "flag4") is False
        assert read_bool_param(args, "missing") is None

    def test_read_list_param(self) -> None:
        """Test list parameter reading."""
        args = {"items": [1, 2, 3]}
        assert read_list_param(args, "items") == [1, 2, 3]
        assert read_list_param(args, "missing") is None
        assert read_list_param(args, "missing", []) == []

    def test_read_dict_param(self) -> None:
        """Test dict parameter reading."""
        args = {"config": {"key": "value"}}
        assert read_dict_param(args, "config") == {"key": "value"}
        assert read_dict_param(args, "missing") is None
        assert read_dict_param(args, "missing", {}) == {}
