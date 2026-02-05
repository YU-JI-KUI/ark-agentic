"""
保险智能体 API 支持模块

提供保险智能体的构建与配置，供统一 FastAPI 服务调用。
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

from .agent import create_insurance_agent, MockLLMClient
from ark_agentic.core.llm import create_llm_client
from ark_agentic.core.runner import AgentRunner

logger = logging.getLogger(__name__)


def create_insurance_agent_from_env(
    sessions_dir: str | Path | None = None,
    enable_persistence: bool = True,
) -> AgentRunner:
    """从环境变量创建保险智能体"""
    provider = os.getenv("LLM_PROVIDER", "deepseek")
    api_key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("GEMINI_API_KEY")
    base_url = os.getenv("LLM_BASE_URL")

    if api_key:
        llm_client = create_llm_client(
            provider=provider,
            api_key=api_key,
            base_url=base_url,
        )
        logger.info(f"Using {provider} LLM client")
    else:
        llm_client = MockLLMClient()
        logger.warning("No API key found, using Mock LLM client")

    if enable_persistence and sessions_dir is None:
        sessions_dir = Path(tempfile.gettempdir()) / "ark_insurance_sessions"
        Path(sessions_dir).mkdir(parents=True, exist_ok=True)

    return create_insurance_agent(
        llm_client=llm_client,
        sessions_dir=sessions_dir,
        enable_persistence=enable_persistence,
    )
