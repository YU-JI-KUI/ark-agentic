"""
证券智能体 API 支持模块

提供证券智能体的构建与配置，供统一 FastAPI 服务调用。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from .agent import create_securities_agent
from ark_agentic.core.llm import create_llm_client, PAModel
from ark_agentic.core.runner import AgentRunner

logger = logging.getLogger(__name__)


def create_securities_agent_from_env(
    sessions_dir: str | Path | None = None,
    enable_persistence: bool = True,
) -> AgentRunner:
    """从环境变量创建证券智能体
    
    环境变量:
        LLM_PROVIDER: LLM 提供商 (pa/deepseek/openai)，默认 pa
        PA_MODEL: PA 模型选择 (PA-JT-80B/PA-SX-80B/PA-SX-235B)，默认 PA-SX-80B
        PA_SX_BASE_URL: PA SX 系列 API 地址
        PA_JT_BASE_URL: PA JT 系列 API 地址
        DEEPSEEK_API_KEY: DeepSeek API Key（当 provider=deepseek 时使用）
        LLM_BASE_URL: 自定义 LLM API 地址
        SESSIONS_DIR: 会话持久化目录
        SECURITIES_SERVICE_MOCK: 是否启用 Mock 模式（true/false），默认 false
        SECURITIES_ACCOUNT_TYPE: 默认账户类型（normal/margin），默认 normal
        SECURITIES_USER_ID: 默认用户 ID，默认 U001
    """
    provider = os.getenv("LLM_PROVIDER", "pa")
    pa_model_str = os.getenv("PA_MODEL", "PA-SX-80B")
    api_key = os.getenv("DEEPSEEK_API_KEY")
    base_url = os.getenv("LLM_BASE_URL")

    if provider == "pa":
        # PA Internal LLM
        try:
            pa_model = PAModel(pa_model_str)
        except ValueError:
            pa_model = PAModel.PA_SX_80B
            logger.warning(f"Invalid PA_MODEL: {pa_model_str}, using PA-SX-80B")
        
        try:
            llm_client = create_llm_client(provider="pa", pa_model=pa_model)
            logger.info(f"Using PA Internal LLM: {pa_model.value}")
        except Exception as e:
            logger.error(f"Failed to create PA LLM client: {e}, falling back to DeepSeek")
            provider = "deepseek"
            # 继续到下面的 deepseek 分支

    if provider == "deepseek":
        # DeepSeek LLM
        if not api_key:
            raise ValueError("DEEPSEEK_API_KEY is required when LLM_PROVIDER=deepseek")
        llm_client = create_llm_client(
            provider="deepseek",
            api_key=api_key,
            base_url=base_url,
        )
        logger.info("Using DeepSeek LLM")
    elif provider == "openai":
        # OpenAI-compatible LLM
        if not api_key:
            raise ValueError("API key is required for OpenAI provider")
        llm_client = create_llm_client(
            provider="openai",
            api_key=api_key,
            base_url=base_url,
        )
        logger.info(f"Using OpenAI-compatible LLM at {base_url or 'default'}")
    elif provider == "mock":
        # Mock LLM for testing
        llm_client = create_llm_client(provider="mock")
        logger.info("Using Mock LLM")

    # 创建证券智能体（已经返回 AgentRunner）
    runner = create_securities_agent(
        llm_client=llm_client,
        sessions_dir=sessions_dir or os.getenv("SESSIONS_DIR"),
        enable_persistence=enable_persistence,
    )
    
    # 记录配置信息
    mock_mode = os.getenv("SECURITIES_SERVICE_MOCK", "").lower() in ("true", "1")
    account_type = os.getenv("SECURITIES_ACCOUNT_TYPE", "normal")
    logger.info(f"Securities Agent created: mock={mock_mode}, account_type={account_type}")
    
    return runner
