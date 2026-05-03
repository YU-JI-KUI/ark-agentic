"""Agent factory: convention-over-configuration builder for AgentRunner.

Public API:
    AgentDef             — declarative per-agent customization (pure data)
    build_standard_agent — wires AgentDef + runtime params into a ready AgentRunner
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from langchain_core.language_models.chat_models import BaseChatModel
from sqlalchemy.ext.asyncio import AsyncEngine

from ark_agentic.core.callbacks import RunnerCallbacks
from ark_agentic.core.compaction import CompactionConfig, LLMSummarizer
from ark_agentic.core.llm import create_chat_model_from_env
from ark_agentic.core.llm.sampling import SamplingConfig
from ark_agentic.core.memory.manager import build_memory_manager
from ark_agentic.core.paths import get_memory_base_dir, prepare_agent_data_dir
from ark_agentic.core.prompt.builder import PromptConfig
from ark_agentic.core.runner import AgentRunner, RunnerConfig
from ark_agentic.core.session import SessionManager
from ark_agentic.core.skills.base import SkillConfig
from ark_agentic.core.skills.loader import SkillLoader
from ark_agentic.core.skills.router import LLMSkillRouter, SkillRouter
from ark_agentic.core.tools.base import AgentTool
from ark_agentic.core.tools.registry import ToolRegistry
from ark_agentic.core.types import SkillLoadMode

logger = logging.getLogger(__name__)


@dataclass
class AgentDef:
    """Declarative per-agent customization — pure data, no runtime dependencies.

    Three required fields identify the agent; all others have sensible defaults.
    Paths (sessions_dir, memory_dir) are derived by convention from agent_id inside
    build_standard_agent(); callers never construct them manually.
    """

    # Identity (required)
    agent_id: str
    agent_name: str
    agent_description: str

    # Prompt customization (optional)
    system_protocol: str = ""
    custom_instructions: str = ""

    # Execution behaviour (optional)
    enable_subtasks: bool = False
    max_turns: int = 10
    skill_load_mode: SkillLoadMode = SkillLoadMode.dynamic


def build_standard_agent(
    defn: AgentDef,
    skills_dir: Path,
    tools: list[AgentTool],
    *,
    llm: BaseChatModel | None = None,
    enable_memory: bool = False,
    enable_dream: bool = False,
    callbacks: RunnerCallbacks | None = None,
    sampling: SamplingConfig | None = None,
    compaction_config: CompactionConfig | None = None,
    skill_router: SkillRouter | None = None,
    db_engine: AsyncEngine | None = None,
) -> AgentRunner:
    """Build an AgentRunner from an AgentDef with convention-derived defaults.

    Conventions applied internally (callers never see these):
        sessions_dir  = data/ark_sessions/{defn.agent_id}
        memory_dir    = data/ark_memory/{defn.agent_id}   (when enable_memory=True)
        SkillConfig.agent_id = defn.agent_id
        CompactionConfig     = context_window=128_000, preserve_recent=4

    Args:
        defn: Declarative agent definition.
        skills_dir: Filesystem path to the agent's skills/ directory.
        tools: Agent-specific tools (runtime objects).
        llm: LLM instance; initialised from env vars when None.
        enable_memory: Enable the memory system.
        enable_dream: Enable background memory distillation (requires enable_memory=True).
        callbacks: Business hooks (context enrichment, auth checks, citation validation).
        sampling: Override the default SamplingConfig.for_chat().
        compaction_config: Override the default CompactionConfig(128_000, 4).
        skill_router: Skill routing strategy. Only valid in dynamic mode.
            None (default in dynamic mode) → factory wires LLMSkillRouter
                using the agent's main LLM.
            <SkillRouter instance> → use it verbatim (custom strategies).
            Passing a router in full mode raises ValueError.
        db_engine: When ``DB_TYPE=sqlite``, pass the app's shared ``AsyncEngine``
            (e.g. ``app.state.db_engine`` from lifespan) so ``SessionManager`` can
            construct ``SqliteSessionRepository``. Ignored when ``DB_TYPE=file``.
    """
    if llm is None:
        llm = create_chat_model_from_env()

    if defn.skill_load_mode == SkillLoadMode.dynamic:
        resolved_router: SkillRouter | None = skill_router or LLMSkillRouter(
            llm_factory=lambda: llm,
            history_window=6,
            timeout=5.0,
        )
    else:
        if skill_router is not None:
            raise ValueError(
                f"skill_router is incompatible with load_mode="
                f"{defn.skill_load_mode.value}; router is only valid in dynamic mode"
            )
        resolved_router = None

    sessions_dir = prepare_agent_data_dir(defn.agent_id)

    skill_config = SkillConfig(
        skill_directories=[str(skills_dir)],
        agent_id=defn.agent_id,
        enable_eligibility_check=True,
        load_mode=defn.skill_load_mode,
    )
    skill_loader = SkillLoader(skill_config)
    try:
        skill_loader.load_from_directories()
        logger.info(
            "Loaded %d skills for agent '%s'",
            len(skill_loader.list_skills()),
            defn.agent_id,
        )
    except Exception as exc:
        logger.warning("Failed to load skills for agent '%s': %s", defn.agent_id, exc)

    compaction = compaction_config or CompactionConfig(
        context_window=128_000, preserve_recent=4
    )
    session_manager = SessionManager(
        sessions_dir=sessions_dir,
        compaction_config=compaction,
        summarizer=LLMSummarizer(llm),
        db_engine=db_engine,
    )

    tool_registry = ToolRegistry()
    tool_registry.register_all(tools)

    memory_manager = None
    dreamer = None
    if enable_memory:
        memory_dir = get_memory_base_dir() / defn.agent_id
        memory_manager = build_memory_manager(memory_dir)

        if enable_dream:
            from .db.config import load_db_config_from_env
            from .memory.dream import MemoryDreamer
            from .storage.factory import build_agent_state_repository

            db_cfg = load_db_config_from_env()
            engine = None
            if db_cfg.db_type == "sqlite":
                from .db.engine import get_async_engine

                engine = get_async_engine(db_cfg)

            state_repo = build_agent_state_repository(
                workspace_dir=memory_dir, engine=engine,
            )
            # Dream calls use the agent's default sampling; previously the
            # runner-side LLMCaller applied a summarization override, but
            # putting that wiring here would re-leak runner internals.
            # Dream output quality is fine with the chat sampling.
            dreamer = MemoryDreamer(
                lambda: llm,
                memory_manager=memory_manager,
                session_repo=session_manager.repository,
                state_repo=state_repo,
            )

    runner_config = RunnerConfig(
        sampling=sampling or SamplingConfig.for_chat(),
        max_turns=defn.max_turns,
        enable_subtasks=defn.enable_subtasks,
        enable_dream=enable_dream,
        prompt_config=PromptConfig(
            agent_name=defn.agent_name,
            agent_description=defn.agent_description,
            system_protocol=defn.system_protocol,
            custom_instructions=defn.custom_instructions,
        ),
        skill_config=skill_config,
        skill_router=resolved_router,
    )

    return AgentRunner(
        llm=llm,
        tool_registry=tool_registry,
        session_manager=session_manager,
        skill_loader=skill_loader,
        config=runner_config,
        memory_manager=memory_manager,
        callbacks=callbacks,
        dreamer=dreamer,
    )
