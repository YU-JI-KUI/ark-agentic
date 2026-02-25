"""
Agent 核心类型定义

参考: openclaw-main/src/agents/types.ts, sessions/types.ts, skills/types.ts
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Literal, Union

from pydantic import BaseModel as _PydanticBaseModel, Field as _Field


class MessageRole(str, Enum):
    """消息角色"""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class ToolResultType(str, Enum):
    """工具结果类型"""

    JSON = "json"
    TEXT = "text"
    IMAGE = "image"
    ERROR = "error"


@dataclass
class ToolCall:
    """工具调用请求

    参考: Anthropic tool_use block
    """

    id: str
    name: str
    arguments: dict[str, Any]

    @classmethod
    def create(cls, name: str, arguments: dict[str, Any]) -> ToolCall:
        return cls(id=f"toolu_{uuid.uuid4().hex[:24]}", name=name, arguments=arguments)


@dataclass
class AgentToolResult:
    """工具调用结果

    参考: openclaw-main/src/agents/tools/common.ts - jsonResult, imageResult
    """

    tool_call_id: str
    result_type: ToolResultType
    content: Union[str, dict[str, Any], list[Any], int, float]
    is_error: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def json_result(
        cls, tool_call_id: str, data: Any, metadata: dict[str, Any] | None = None
    ) -> AgentToolResult:
        """创建 JSON 结果"""
        return cls(
            tool_call_id=tool_call_id,
            result_type=ToolResultType.JSON,
            content=data,
            metadata=metadata or {},
        )

    @classmethod
    def text_result(
        cls, tool_call_id: str, text: str, metadata: dict[str, Any] | None = None
    ) -> AgentToolResult:
        """创建文本结果"""
        return cls(
            tool_call_id=tool_call_id,
            result_type=ToolResultType.TEXT,
            content=text,
            metadata=metadata or {},
        )

    @classmethod
    def image_result(
        cls,
        tool_call_id: str,
        base64_data: str,
        media_type: str = "image/png",
        metadata: dict[str, Any] | None = None,
    ) -> AgentToolResult:
        """创建图片结果"""
        return cls(
            tool_call_id=tool_call_id,
            result_type=ToolResultType.IMAGE,
            content={"data": base64_data, "media_type": media_type},
            metadata=metadata or {},
        )

    @classmethod
    def error_result(
        cls, tool_call_id: str, error: str, metadata: dict[str, Any] | None = None
    ) -> AgentToolResult:
        """创建错误结果"""
        return cls(
            tool_call_id=tool_call_id,
            result_type=ToolResultType.ERROR,
            content=error,
            is_error=True,
            metadata=metadata or {},
        )


@dataclass
class AgentMessage:
    """智能体消息

    参考: openclaw-main/src/agents/types.ts - AgentMessage
    """

    role: MessageRole
    content: str | None = None
    tool_calls: list[ToolCall] | None = None
    tool_results: list[AgentToolResult] | None = None
    thinking: str | None = None  # 思考过程（extended thinking）
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def system(cls, content: str) -> AgentMessage:
        return cls(role=MessageRole.SYSTEM, content=content)

    @classmethod
    def user(cls, content: str, metadata: dict[str, Any] | None = None) -> AgentMessage:
        return cls(role=MessageRole.USER, content=content, metadata=metadata or {})

    @classmethod
    def assistant(
        cls,
        content: str | None = None,
        tool_calls: list[ToolCall] | None = None,
        thinking: str | None = None,
    ) -> AgentMessage:
        return cls(
            role=MessageRole.ASSISTANT,
            content=content,
            tool_calls=tool_calls,
            thinking=thinking,
        )

    @classmethod
    def tool(cls, results: list[AgentToolResult]) -> AgentMessage:
        return cls(role=MessageRole.TOOL, tool_results=results)


# ============ Skill Types ============


@dataclass
class SkillMetadata:
    """技能元数据

    参考: openclaw-main/src/agents/skills/types.ts - OpenClawSkillMetadata
    """

    # 基础信息
    name: str
    description: str
    version: str = "1.0.0"

    # 环境要求
    required_os: list[str] | None = None  # ["windows", "linux", "darwin"]
    required_binaries: list[str] | None = None  # ["python", "node"]
    required_env_vars: list[str] | None = None  # ["API_KEY"]

    # 调用策略
    invocation_policy: Literal["auto", "manual", "always"] = "auto"

    # 工具依赖
    required_tools: list[str] | None = None

    # 分组和标签
    group: str | None = None
    tags: list[str] = field(default_factory=list)

    # 何时使用（简短说明，用于“是否加载该技能”决策）
    when_to_use: str | None = None


@dataclass
class SkillEntry:
    """技能条目

    参考: openclaw-main/src/agents/skills/types.ts - SkillEntry
    """

    # 唯一标识（通常为目录名）
    id: str

    # 技能路径
    path: str

    # 技能内容（SKILL.md 的内容）
    content: str

    # 元数据（从 frontmatter 解析）
    metadata: SkillMetadata

    # 来源优先级（数字越小优先级越高）
    source_priority: int = 0

    # 是否启用
    enabled: bool = True


# ============ Run Options ============


class SkillLoadMode(str, Enum):
    """技能加载模式"""

    full = "full"
    dynamic = "dynamic"
    semantic = "semantic"


class RunOptions(_PydanticBaseModel):
    """单次运行的选项（模型、温度等）。

    用于 API 层按请求覆盖模型和温度。
    技能加载模式由 SkillConfig.default_load_mode 在 Agent 级别配置,
    不在单次请求中指定。
    """

    model: str | None = _Field(None, description="模型名称覆盖")
    temperature: float | None = _Field(None, ge=0.0, le=2.0, description="采样温度覆盖（0.0-2.0）")


# ============ Session Types ============


@dataclass
class TokenUsage:
    """Token 使用统计"""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass
class CompactionStats:
    """压缩统计"""

    original_messages: int = 0
    compacted_messages: int = 0
    original_tokens: int = 0
    compacted_tokens: int = 0
    last_compaction_at: datetime | None = None


@dataclass
class SessionEntry:
    """会话条目

    参考: openclaw-main/src/config/sessions/types.ts - SessionEntry
    """

    # 会话标识
    session_id: str
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    # 模型配置
    model: str = "Qwen3-80B-Instruct"
    provider: str = "ark"

    # 消息历史
    messages: list[AgentMessage] = field(default_factory=list)

    # Token 统计
    token_usage: TokenUsage = field(default_factory=TokenUsage)

    # 压缩状态
    compaction_stats: CompactionStats = field(default_factory=CompactionStats)

    # 活跃技能快照
    active_skills: list[str] = field(default_factory=list)

    # 会话元数据
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls, model: str = "Qwen3-80B-Instruct", provider: str = "ark", **kwargs: Any
    ) -> SessionEntry:
        return cls(
            session_id=str(uuid.uuid4()),
            model=model,
            provider=provider,
            **kwargs,
        )

    def add_message(self, message: AgentMessage) -> None:
        """添加消息到历史"""
        self.messages.append(message)
        self.updated_at = datetime.now()

    def update_token_usage(
        self,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        cache_read: int = 0,
        cache_creation: int = 0,
    ) -> None:
        self.token_usage.prompt_tokens += prompt_tokens
        self.token_usage.completion_tokens += completion_tokens
        self.token_usage.cache_read_tokens += cache_read
        self.token_usage.cache_creation_tokens += cache_creation
