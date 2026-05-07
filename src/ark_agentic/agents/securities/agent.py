"""
证券资产管理 Agent — BaseAgent 子类。

环境变量:
    SESSIONS_DIR: 会话持久化基础目录（默认 data/ark_sessions）
    MEMORY_DIR:   Memory 数据基础目录（默认 data/ark_memory）
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ark_agentic import BaseAgent
from ark_agentic.core.runtime.callbacks import (
    CallbackContext,
    CallbackEvent,
    CallbackResult,
    HookAction,
    RunnerCallbacks,
)
from ark_agentic.core.runtime.validation import EntityTrie, create_citation_validation_hook
from ark_agentic.core.types import AgentMessage

from .tools import create_securities_tools
from .tools.service.param_mapping import _get_context_value, enrich_securities_context
from .validation import VALIDATION_SYSTEM_INSTRUCTION

logger = logging.getLogger(__name__)

_AGENT_DIR = Path(__file__).resolve().parent
_STOCKS_CSV = _AGENT_DIR / "mock_data" / "stocks" / "a_shares_seed.csv"


async def _enrich_context(ctx: CallbackContext, **kwargs: Any) -> CallbackResult | None:
    return CallbackResult(context_updates=enrich_securities_context(ctx.input_context))


async def _auth_check(ctx: CallbackContext, **kwargs: Any) -> CallbackResult | None:
    login_flag = _get_context_value(ctx.input_context, "loginflag")
    if str(login_flag) != "1":
        return None
    account_type = _get_context_value(ctx.input_context, "account_type", "normal")
    type_code = "1" if account_type == "margin" else "2"
    return CallbackResult(
        action=HookAction.ABORT,
        response=AgentMessage.assistant("需要进行证券账户登录才能访问该服务。"),
        event=CallbackEvent(
            type="ui_component",
            data={
                "template": "common_login",
                "body": {"actionAuth": "Z", "type": type_code},
            },
        ),
    )


class SecuritiesAgent(BaseAgent):
    """证券资产管理 Agent"""

    agent_id = "securities"
    agent_name = "证券资产管理助手"
    agent_description = "专业的证券资产查询与分析助手"
    custom_instructions = VALIDATION_SYSTEM_INSTRUCTION

    def build_tools(self):
        return create_securities_tools()

    def build_callbacks(self) -> RunnerCallbacks | None:
        trie = EntityTrie()
        trie.load_from_csv(_STOCKS_CSV)
        return RunnerCallbacks(
            before_agent=[_enrich_context, _auth_check],
            before_loop_end=[create_citation_validation_hook(entity_trie=trie)],
        )
