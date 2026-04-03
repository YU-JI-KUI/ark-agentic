"""
Agent Tools - 工具系统

提供工具基类、注册器和辅助函数。
"""

from .base import (
    AgentTool,
    ToolParameter,
    read_string_param,
    read_int_param,
    read_float_param,
    read_bool_param,
    read_list_param,
    read_dict_param,
)
from .executor import ToolExecutor
from .registry import ToolRegistry
from .memory import MemorySearchTool, MemoryGetTool, create_memory_tools
from .pa_knowledge_api import PAKnowledgeAPIConfig, PAKnowledgeAPITool, create_pa_knowledge_api_tool
from .demo_state import SetStateDemoTool, GetStateDemoTool
from .render_a2ui import BlocksConfig, CardExtractor, RenderA2UITool, TemplateConfig

__all__ = [
    # Base
    "AgentTool",
    "ToolParameter",
    "ToolExecutor",
    "ToolRegistry",
    # Parameter helpers
    "read_string_param",
    "read_int_param",
    "read_float_param",
    "read_bool_param",
    "read_list_param",
    "read_dict_param",
    # Memory tools
    "MemorySearchTool",
    "MemoryGetTool",
    "create_memory_tools",
    # PA Knowledge API tool (optional, register via runner.register_tool())
    "PAKnowledgeAPIConfig",
    "PAKnowledgeAPITool",
    "create_pa_knowledge_api_tool",
    # Demo state tools (session state read/write)
    "SetStateDemoTool",
    "GetStateDemoTool",
    # A2UI rendering tools
    "BlocksConfig",
    "CardExtractor",
    "RenderA2UITool",
    "TemplateConfig",
]
