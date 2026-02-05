"""
工具注册器

参考: openclaw-main/src/agents/openclaw-tools.ts
"""

from __future__ import annotations

from typing import Any

from .base import AgentTool


class ToolRegistry:
    """工具注册器

    管理工具的注册、查找和 schema 生成。
    """

    def __init__(self) -> None:
        self._tools: dict[str, AgentTool] = {}
        self._groups: dict[str, list[str]] = {}  # group -> tool names

    def register(self, tool: AgentTool) -> None:
        """注册工具"""
        if tool.name in self._tools:
            raise ValueError(f"Tool '{tool.name}' is already registered")
        self._tools[tool.name] = tool

        # 注册到分组
        if tool.group:
            if tool.group not in self._groups:
                self._groups[tool.group] = []
            self._groups[tool.group].append(tool.name)

    def register_all(self, tools: list[AgentTool]) -> None:
        """批量注册工具"""
        for tool in tools:
            self.register(tool)

    def get(self, name: str) -> AgentTool | None:
        """按名称获取工具"""
        return self._tools.get(name)

    def get_required(self, name: str) -> AgentTool:
        """按名称获取工具（必须存在）"""
        tool = self.get(name)
        if tool is None:
            raise KeyError(f"Tool '{name}' not found")
        return tool

    def get_by_group(self, group: str) -> list[AgentTool]:
        """按分组获取工具"""
        tool_names = self._groups.get(group, [])
        return [self._tools[name] for name in tool_names if name in self._tools]

    def list_all(self) -> list[AgentTool]:
        """列出所有工具"""
        return list(self._tools.values())

    def list_names(self) -> list[str]:
        """列出所有工具名称"""
        return list(self._tools.keys())

    def list_groups(self) -> list[str]:
        """列出所有分组"""
        return list(self._groups.keys())

    def has(self, name: str) -> bool:
        """检查工具是否存在"""
        return name in self._tools

    def unregister(self, name: str) -> bool:
        """取消注册工具

        Returns:
            True 如果成功取消注册，False 如果工具不存在
        """
        if name in self._tools:
            tool = self._tools.pop(name)
            # 从分组中移除
            if tool.group and tool.group in self._groups:
                self._groups[tool.group] = [
                    n for n in self._groups[tool.group] if n != name
                ]
            return True
        return False

    def clear(self) -> None:
        """清空所有工具"""
        self._tools.clear()
        self._groups.clear()

    def get_schemas(
        self,
        names: list[str] | None = None,
        groups: list[str] | None = None,
        exclude: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """获取工具的 JSON Schema 列表

        Args:
            names: 指定工具名称列表（None 表示全部）
            groups: 指定分组列表
            exclude: 排除的工具名称列表

        Returns:
            JSON Schema 列表（用于 LLM function calling）
        """
        tools_to_include: set[str] = set()

        if names is not None:
            tools_to_include.update(names)
        elif groups is not None:
            for group in groups:
                tools_to_include.update(self._groups.get(group, []))
        else:
            tools_to_include.update(self._tools.keys())

        # 应用排除列表
        if exclude:
            tools_to_include -= set(exclude)

        return [
            self._tools[name].get_json_schema()
            for name in tools_to_include
            if name in self._tools
        ]

    def filter(
        self,
        allow: list[str] | None = None,
        deny: list[str] | None = None,
        allow_groups: list[str] | None = None,
        deny_groups: list[str] | None = None,
    ) -> list[AgentTool]:
        """根据策略过滤工具

        Phase 1 简化版策略过滤。

        Args:
            allow: 允许的工具名称（白名单）
            deny: 拒绝的工具名称（黑名单）
            allow_groups: 允许的分组
            deny_groups: 拒绝的分组

        Returns:
            过滤后的工具列表
        """
        result: set[str] = set()

        # 构建初始集合
        if allow is not None:
            result.update(allow)
        elif allow_groups is not None:
            for group in allow_groups:
                result.update(self._groups.get(group, []))
        else:
            result.update(self._tools.keys())

        # 应用拒绝列表
        if deny:
            result -= set(deny)
        if deny_groups:
            for group in deny_groups:
                result -= set(self._groups.get(group, []))

        return [self._tools[name] for name in result if name in self._tools]

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def __iter__(self):
        return iter(self._tools.values())
