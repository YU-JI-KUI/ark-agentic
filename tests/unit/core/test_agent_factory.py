"""Tests for ``BaseAgent`` declarative wiring (replaces the old factory tests).

The ``AgentDef`` dataclass + ``build_standard_agent`` factory were merged
into ``BaseAgent.__init__``; subclass identity comes from ``ClassVar``
attributes and the ``build_*`` hooks.
"""
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ark_agentic.core.runtime.base_agent import BaseAgent
from ark_agentic.core.types import SkillLoadMode


def _make_subclass(
    *,
    agent_id: str = "test",
    agent_name: str = "Test Agent",
    agent_description: str = "A test agent.",
    system_protocol: str = "",
    custom_instructions: str = "",
    enable_subtasks: bool = False,
    max_turns: int = 10,
    skill_load_mode: SkillLoadMode = SkillLoadMode.dynamic,
):
    """Build a fresh BaseAgent subclass with the given ClassVar overrides."""
    return type(
        "Test_" + agent_id,
        (BaseAgent,),
        {
            "agent_id": agent_id,
            "agent_name": agent_name,
            "agent_description": agent_description,
            "system_protocol": system_protocol,
            "custom_instructions": custom_instructions,
            "enable_subtasks": enable_subtasks,
            "max_turns": max_turns,
            "skill_load_mode": skill_load_mode,
        },
    )


class TestBaseAgentValidation:
    def test_base_agent_cannot_be_instantiated_directly(self):
        with pytest.raises(TypeError, match="cannot be instantiated"):
            BaseAgent()

    def test_subclass_without_agent_id_raises(self):
        cls = type("NoId", (BaseAgent,), {})
        with pytest.raises(TypeError, match="declare a class-level 'agent_id'"):
            cls()

    def test_subclass_with_empty_agent_id_raises(self):
        cls = type("Empty", (BaseAgent,), {"agent_id": ""})
        with pytest.raises(TypeError, match="non-empty string"):
            cls()


class TestBaseAgentDeclarativeWiring:
    @pytest.fixture(autouse=True)
    def _force_file_db_type(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DB_TYPE", "file")

    def _instantiate(self, cls, tmp_path: Path):
        mock_llm = MagicMock()
        with patch.object(BaseAgent, "build_llm", return_value=mock_llm), \
             patch("ark_agentic.core.runtime.base_agent.prepare_agent_data_dir", return_value=tmp_path), \
             patch("ark_agentic.core.runtime.base_agent.get_memory_base_dir", return_value=tmp_path):
            return cls(), mock_llm

    def test_subclass_produces_base_agent(self, tmp_path):
        cls = _make_subclass()
        agent, _ = self._instantiate(cls, tmp_path)
        assert isinstance(agent, BaseAgent)

    def test_agent_id_propagated_to_skill_config(self, tmp_path):
        cls = _make_subclass(agent_id="my_agent")
        agent, _ = self._instantiate(cls, tmp_path)
        assert agent.config.skill_config.agent_id == "my_agent"

    def test_prompt_config_built_from_class_attrs(self, tmp_path):
        cls = _make_subclass(
            agent_id="ins",
            agent_name="保险助手",
            agent_description="专业保险咨询",
            system_protocol="禁止重复卡片内容",
            custom_instructions="验证规则",
        )
        agent, _ = self._instantiate(cls, tmp_path)
        assert agent.config.prompt_config.agent_name == "保险助手"
        assert agent.config.prompt_config.system_protocol == "禁止重复卡片内容"
        assert agent.config.prompt_config.custom_instructions == "验证规则"

    def test_enable_memory_false_means_no_memory_manager(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.delenv("ENABLE_MEMORY", raising=False)
        cls = _make_subclass()
        agent, _ = self._instantiate(cls, tmp_path)
        assert agent._memory_manager is None

    def test_enable_memory_true_creates_memory_manager(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("ENABLE_MEMORY", "true")
        mock_memory = MagicMock()
        with patch(
            "ark_agentic.core.runtime.base_agent.build_memory_manager",
            return_value=mock_memory,
        ):
            cls = _make_subclass()
            agent, _ = self._instantiate(cls, tmp_path)
        assert agent._memory_manager is mock_memory

    def test_build_llm_default_calls_create_from_env(self, tmp_path):
        mock_llm = MagicMock()
        with patch(
            "ark_agentic.core.runtime.base_agent.create_chat_model_from_env",
            return_value=mock_llm,
        ) as mock_factory, \
             patch(
                 "ark_agentic.core.runtime.base_agent.prepare_agent_data_dir",
                 return_value=tmp_path,
             ), \
             patch(
                 "ark_agentic.core.runtime.base_agent.get_memory_base_dir",
                 return_value=tmp_path,
             ):
            cls = _make_subclass()
            agent = cls()
        mock_factory.assert_called_once()
        assert agent.llm is mock_llm

    def test_enable_subtasks_propagated(self, tmp_path):
        cls = _make_subclass(enable_subtasks=True)
        agent, _ = self._instantiate(cls, tmp_path)
        assert agent.config.enable_subtasks is True

    def test_skills_dir_added_to_skill_config(self, tmp_path):
        cls = _make_subclass()
        # Override skills_dir property at class level so it points at tmp_path
        cls.skills_dir = property(lambda self: tmp_path / "skills")
        (tmp_path / "skills").mkdir()
        agent, _ = self._instantiate(cls, tmp_path)
        assert str(tmp_path / "skills") in agent.config.skill_config.skill_directories
