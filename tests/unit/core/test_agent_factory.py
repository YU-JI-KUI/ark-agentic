"""Tests for AgentDef dataclass and build_standard_agent factory."""
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ark_agentic.core.runtime.factory import AgentDef, build_standard_agent
from ark_agentic.core.runtime.runner import AgentRunner
from ark_agentic.core.types import SkillLoadMode


class TestAgentDef:
    def test_required_fields_accepted(self):
        defn = AgentDef(
            agent_id="lending",
            agent_name="贷款助手",
            agent_description="贷款咨询助手。",
        )
        assert defn.agent_id == "lending"
        assert defn.agent_name == "贷款助手"
        assert defn.agent_description == "贷款咨询助手。"

    def test_defaults(self):
        defn = AgentDef(agent_id="x", agent_name="X", agent_description="X.")
        assert defn.system_protocol == ""
        assert defn.custom_instructions == ""
        assert defn.enable_subtasks is False
        assert defn.max_turns == 10
        assert defn.skill_load_mode == SkillLoadMode.dynamic

    def test_custom_optional_fields(self):
        defn = AgentDef(
            agent_id="insurance",
            agent_name="保险助手",
            agent_description="保险咨询。",
            system_protocol="禁止重复卡片内容",
            enable_subtasks=True,
            max_turns=15,
        )
        assert defn.enable_subtasks is True
        assert defn.max_turns == 15
        assert defn.system_protocol == "禁止重复卡片内容"

    def test_missing_required_field_raises(self):
        with pytest.raises(TypeError):
            AgentDef(agent_name="X", agent_description="X.")  # missing agent_id


class TestBuildStandardAgent:
    @pytest.fixture(autouse=True)
    def _force_file_db_type(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """build_standard_agent defaults db_engine=None; sqlite mode requires an engine."""
        monkeypatch.setenv("DB_TYPE", "file")

    def _make_def(self, agent_id: str = "test") -> AgentDef:
        return AgentDef(
            agent_id=agent_id,
            agent_name="Test Agent",
            agent_description="A test agent.",
        )

    def test_returns_agent_runner(self, tmp_path):
        mock_llm = MagicMock()
        with patch("ark_agentic.core.runtime.factory.prepare_agent_data_dir", return_value=tmp_path), \
             patch("ark_agentic.core.runtime.factory.get_memory_base_dir", return_value=tmp_path):
            runner = build_standard_agent(
                self._make_def(), skills_dir=tmp_path, tools=[], llm=mock_llm
            )
        assert isinstance(runner, AgentRunner)

    def test_agent_id_propagated_to_skill_config(self, tmp_path):
        mock_llm = MagicMock()
        with patch("ark_agentic.core.runtime.factory.prepare_agent_data_dir", return_value=tmp_path), \
             patch("ark_agentic.core.runtime.factory.get_memory_base_dir", return_value=tmp_path):
            runner = build_standard_agent(
                self._make_def("my_agent"), skills_dir=tmp_path, tools=[], llm=mock_llm
            )
        assert runner.config.skill_config.agent_id == "my_agent"

    def test_prompt_config_built_from_def(self, tmp_path):
        mock_llm = MagicMock()
        defn = AgentDef(
            agent_id="ins",
            agent_name="保险助手",
            agent_description="专业保险咨询",
            system_protocol="禁止重复卡片内容",
            custom_instructions="验证规则",
        )
        with patch("ark_agentic.core.runtime.factory.prepare_agent_data_dir", return_value=tmp_path), \
             patch("ark_agentic.core.runtime.factory.get_memory_base_dir", return_value=tmp_path):
            runner = build_standard_agent(defn, skills_dir=tmp_path, tools=[], llm=mock_llm)
        assert runner.config.prompt_config.agent_name == "保险助手"
        assert runner.config.prompt_config.system_protocol == "禁止重复卡片内容"
        assert runner.config.prompt_config.custom_instructions == "验证规则"

    def test_enable_memory_false_means_no_memory_manager(self, tmp_path):
        mock_llm = MagicMock()
        with patch("ark_agentic.core.runtime.factory.prepare_agent_data_dir", return_value=tmp_path):
            runner = build_standard_agent(
                self._make_def(), skills_dir=tmp_path, tools=[], llm=mock_llm, enable_memory=False
            )
        assert runner._memory_manager is None

    def test_enable_memory_true_creates_memory_manager(self, tmp_path):
        mock_llm = MagicMock()
        mock_memory = MagicMock()
        with patch("ark_agentic.core.runtime.factory.prepare_agent_data_dir", return_value=tmp_path), \
             patch("ark_agentic.core.runtime.factory.get_memory_base_dir", return_value=tmp_path), \
             patch("ark_agentic.core.runtime.factory.build_memory_manager", return_value=mock_memory):
            runner = build_standard_agent(
                self._make_def(), skills_dir=tmp_path, tools=[], llm=mock_llm, enable_memory=True
            )
        assert runner._memory_manager is mock_memory

    def test_llm_none_calls_create_from_env(self, tmp_path):
        mock_llm = MagicMock()
        with patch("ark_agentic.core.runtime.factory.prepare_agent_data_dir", return_value=tmp_path), \
             patch("ark_agentic.core.runtime.factory.get_memory_base_dir", return_value=tmp_path), \
             patch("ark_agentic.core.runtime.factory.create_chat_model_from_env", return_value=mock_llm) as mock_factory:
            runner = build_standard_agent(self._make_def(), skills_dir=tmp_path, tools=[], llm=None)
        mock_factory.assert_called_once()
        assert runner.llm is mock_llm

    def test_enable_subtasks_propagated(self, tmp_path):
        mock_llm = MagicMock()
        defn = AgentDef(agent_id="x", agent_name="X", agent_description="X.", enable_subtasks=True)
        with patch("ark_agentic.core.runtime.factory.prepare_agent_data_dir", return_value=tmp_path), \
             patch("ark_agentic.core.runtime.factory.get_memory_base_dir", return_value=tmp_path):
            runner = build_standard_agent(defn, skills_dir=tmp_path, tools=[], llm=mock_llm)
        assert runner.config.enable_subtasks is True

    def test_skills_dir_added_to_skill_config(self, tmp_path):
        mock_llm = MagicMock()
        skills_path = tmp_path / "skills"
        skills_path.mkdir()
        with patch("ark_agentic.core.runtime.factory.prepare_agent_data_dir", return_value=tmp_path), \
             patch("ark_agentic.core.runtime.factory.get_memory_base_dir", return_value=tmp_path):
            runner = build_standard_agent(
                self._make_def(), skills_dir=skills_path, tools=[], llm=mock_llm
            )
        assert str(skills_path) in runner.config.skill_config.skill_directories
