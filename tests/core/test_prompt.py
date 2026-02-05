"""Tests for prompt builder."""

import pytest
from ark_agentic.core.prompt.builder import (
    INSURANCE_AGENT_INSTRUCTIONS,
    PromptConfig,
    SystemPromptBuilder,
    build_insurance_agent_prompt,
)
from ark_agentic.core.tools.base import AgentTool, ToolParameter
from ark_agentic.core.types import AgentToolResult, SkillEntry, SkillMetadata


class MockTool(AgentTool):
    """Mock tool for testing."""

    name = "mock_tool"
    description = "A mock tool for testing"
    parameters = [
        ToolParameter(
            name="query",
            type="string",
            description="Query parameter"
        )
    ]

    async def execute(self, tool_call, context=None):
        return AgentToolResult.text_result(tool_call.id, "done")


class TestPromptConfig:
    """Tests for PromptConfig."""

    def test_default_values(self) -> None:
        """Test default configuration values."""
        config = PromptConfig()
        assert config.agent_name == "Assistant"
        assert config.include_datetime
        assert config.timezone == "Asia/Shanghai"

    def test_custom_values(self) -> None:
        """Test custom configuration values."""
        config = PromptConfig(
            agent_name="CustomBot",
            include_datetime=False,
            custom_instructions="Be helpful."
        )
        assert config.agent_name == "CustomBot"
        assert not config.include_datetime
        assert config.custom_instructions == "Be helpful."


class TestSystemPromptBuilder:
    """Tests for SystemPromptBuilder."""

    def test_add_identity(self) -> None:
        """Test adding identity section."""
        builder = SystemPromptBuilder()
        builder.add_identity(name="TestBot", description="A test bot")
        prompt = builder.build()

        assert "TestBot" in prompt
        assert "A test bot" in prompt

    def test_add_identity_from_config(self) -> None:
        """Test adding identity from config."""
        config = PromptConfig(agent_name="ConfigBot", agent_description="Bot from config")
        builder = SystemPromptBuilder(config)
        builder.add_identity()
        prompt = builder.build()

        assert "ConfigBot" in prompt
        assert "Bot from config" in prompt

    def test_add_runtime_info(self) -> None:
        """Test adding runtime information."""
        config = PromptConfig(include_datetime=True, timezone="UTC")
        builder = SystemPromptBuilder(config)
        builder.add_runtime_info()
        prompt = builder.build()

        assert "Runtime Information" in prompt
        assert "UTC" in prompt

    def test_add_runtime_info_disabled(self) -> None:
        """Test runtime info disabled."""
        config = PromptConfig(include_datetime=False)
        builder = SystemPromptBuilder(config)
        builder.add_runtime_info()
        prompt = builder.build()

        # Should not have runtime section
        assert "Runtime Information" not in prompt

    def test_add_tools(self) -> None:
        """Test adding tools section."""
        builder = SystemPromptBuilder()
        tools = [MockTool()]
        builder.add_tools(tools)
        prompt = builder.build()

        assert "Available Tools" in prompt
        assert "mock_tool" in prompt
        assert "A mock tool for testing" in prompt

    def test_add_tools_with_params(self) -> None:
        """Test adding tools with parameter info."""
        builder = SystemPromptBuilder()
        tools = [MockTool()]
        builder.add_tools(tools, include_params=True)
        prompt = builder.build()

        assert "query(string)" in prompt

    def test_add_tools_disabled(self) -> None:
        """Test tools disabled in config."""
        config = PromptConfig(include_tool_descriptions=False)
        builder = SystemPromptBuilder(config)
        builder.add_tools([MockTool()])
        prompt = builder.build()

        assert "Available Tools" not in prompt

    def test_add_skills(self) -> None:
        """Test adding skills section."""
        builder = SystemPromptBuilder()
        skills = [
            SkillEntry(
                id="test_skill",
                path="/test",
                content="Use this skill when testing.",
                metadata=SkillMetadata(name="Test Skill", description="A test skill"),
            )
        ]
        builder.add_skills(skills)
        prompt = builder.build()

        assert "Test Skill" in prompt
        assert "Use this skill when testing." in prompt

    def test_add_skills_disabled(self) -> None:
        """Test skills disabled in config."""
        config = PromptConfig(include_skill_descriptions=False)
        builder = SystemPromptBuilder(config)
        skills = [
            SkillEntry(
                id="test",
                path="/test",
                content="Content",
                metadata=SkillMetadata(name="Test", description="Test"),
            )
        ]
        builder.add_skills(skills)
        prompt = builder.build()

        # Skills section should not be added
        assert "Test Skill" not in prompt

    def test_add_custom_instructions(self) -> None:
        """Test adding custom instructions."""
        builder = SystemPromptBuilder()
        builder.add_custom_instructions("Always be polite.")
        prompt = builder.build()

        assert "Instructions" in prompt
        assert "Always be polite." in prompt

    def test_add_custom_instructions_from_config(self) -> None:
        """Test custom instructions from config."""
        config = PromptConfig(custom_instructions="Be helpful and concise.")
        builder = SystemPromptBuilder(config)
        builder.add_custom_instructions()
        prompt = builder.build()

        assert "Be helpful and concise." in prompt

    def test_add_context(self) -> None:
        """Test adding context."""
        builder = SystemPromptBuilder()
        context = {
            "user_name": "John",
            "preferences": {"theme": "dark", "language": "zh"},
            "tags": ["premium", "beta"],
        }
        builder.add_context(context)
        prompt = builder.build()

        assert "Context" in prompt
        assert "user_name" in prompt
        assert "John" in prompt
        assert "dark" in prompt
        assert "premium" in prompt

    def test_add_section(self) -> None:
        """Test adding custom section."""
        builder = SystemPromptBuilder()
        builder.add_section("custom", "This is a custom section.")
        prompt = builder.build()

        assert "This is a custom section." in prompt

    def test_add_section_empty_content(self) -> None:
        """Test adding section with empty content."""
        builder = SystemPromptBuilder()
        builder.add_section("empty", "")
        builder.add_section("whitespace", "   ")
        # Should not add empty sections
        assert len(builder._sections) == 0

    def test_reset(self) -> None:
        """Test builder reset."""
        builder = SystemPromptBuilder()
        builder.add_identity()
        builder.reset()
        assert len(builder._sections) == 0

    def test_build_default(self) -> None:
        """Test default build behavior."""
        builder = SystemPromptBuilder()
        prompt = builder.build()

        # Should have identity and runtime by default
        assert "Assistant" in prompt

    def test_section_separator(self) -> None:
        """Test sections are separated."""
        builder = SystemPromptBuilder()
        builder.add_identity()
        builder.add_custom_instructions("Be helpful.")
        prompt = builder.build()

        # Sections should be separated by ---
        assert "---" in prompt


class TestQuickBuild:
    """Tests for quick_build class method."""

    def test_quick_build_basic(self) -> None:
        """Test basic quick build."""
        prompt = SystemPromptBuilder.quick_build()
        assert "Assistant" in prompt

    def test_quick_build_with_tools(self) -> None:
        """Test quick build with tools."""
        prompt = SystemPromptBuilder.quick_build(
            tools=[MockTool()]
        )
        assert "mock_tool" in prompt

    def test_quick_build_with_skills(self) -> None:
        """Test quick build with skills."""
        skills = [
            SkillEntry(
                id="test",
                path="/test",
                content="Skill content",
                metadata=SkillMetadata(name="Test", description="Test"),
            )
        ]
        prompt = SystemPromptBuilder.quick_build(skills=skills)
        assert "Skill content" in prompt

    def test_quick_build_with_context(self) -> None:
        """Test quick build with context."""
        prompt = SystemPromptBuilder.quick_build(
            context={"key": "value"}
        )
        assert "key" in prompt
        assert "value" in prompt

    def test_quick_build_with_custom_instructions(self) -> None:
        """Test quick build with custom instructions."""
        prompt = SystemPromptBuilder.quick_build(
            custom_instructions="Follow these rules."
        )
        assert "Follow these rules." in prompt

    def test_quick_build_with_tool_params(self) -> None:
        """Test quick build with tool params."""
        prompt = SystemPromptBuilder.quick_build(
            tools=[MockTool()],
            include_tool_params=True
        )
        assert "query(string)" in prompt


class TestBuildInsuranceAgentPrompt:
    """Tests for insurance agent prompt builder."""

    def test_basic_prompt(self) -> None:
        """Test basic insurance prompt."""
        prompt = build_insurance_agent_prompt()

        assert "保险智能助手" in prompt
        assert "工作流程" in prompt or "理解需求" in prompt

    def test_with_tools(self) -> None:
        """Test with tools."""
        prompt = build_insurance_agent_prompt(
            tools=[MockTool()]
        )
        assert "mock_tool" in prompt

    def test_with_user_context(self) -> None:
        """Test with user context."""
        prompt = build_insurance_agent_prompt(
            user_context={"customer_id": "12345"}
        )
        assert "customer_id" in prompt

    def test_insurance_instructions_content(self) -> None:
        """Test insurance instructions content."""
        assert "保险" in INSURANCE_AGENT_INSTRUCTIONS
        assert "方案" in INSURANCE_AGENT_INSTRUCTIONS
