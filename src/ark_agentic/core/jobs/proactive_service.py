"""ProactiveServiceJob — 主动服务 Job

流程：
  1. should_process_user: 关键词快速扫描 MEMORY.md，判断是否有主动服务意图
  2. process_user:
     a. LLM 提取结构化意图（stock_alert / remind 等）
     b. 根据意图调用对应工具（直接调用，不走 AgentRunner ReAct 循环）
     c. LLM 生成自然语言通知文本
     d. 返回 Notification 列表
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any, Callable

from .base import BaseJob, JobMeta
from ..notifications.models import Notification

if TYPE_CHECKING:
    from langchain_core.language_models.chat_models import BaseChatModel

    from ..tools.registry import ToolRegistry
    from ..memory.manager import MemoryManager

logger = logging.getLogger(__name__)

# ── 关键词：快速规则过滤 ─────────────────────────────────────────────────────
_INTENT_KEYWORDS = [
    "关注", "提醒", "通知我", "盯着", "跌到", "涨到", "到价",
    "目标价", "股价", "基金净值", "持续关注", "跟踪",
]

# ── LLM Prompt：意图提取 ───────────────────────────────────────────────────
_INTENT_EXTRACT_PROMPT = """\
你是一个主动服务引擎。分析用户的记忆文件，判断今天（{today}）是否有需要主动推送的信息。

## 用户记忆
{memory}

## 任务
识别用户是否有以下类型的主动服务意图：
- stock_alert: 关注某只股票/基金的价格变化（如"关注平安股价"、"跌到30元提醒我"）
- remind: 定期提醒（如"每周一提醒我查看持仓"）
- other: 其他可主动推送的场景

## 输出要求
输出严格 JSON（无 markdown 代码块）：
{{"intents": [{{"type": "stock_alert", "symbol": "中国平安", "condition": "price_drop", "threshold": null, "description": "用户关注中国平安股价"}}]}}
若无可主动服务的场景，输出：{{"intents": []}}

注意：
- symbol 使用用户原始表述（如"平安"、"腾讯"、"600519"）
- condition 可为：price_drop（价格下跌）、price_rise（价格上涨）、price_target（目标价）、daily_update（每日更新）
- threshold 为触发条件的阈值（如目标价格），无明确阈值则为 null
"""

# ── LLM Prompt：通知文本生成 ─────────────────────────────────────────────────
_NOTIFY_PROMPT = """\
根据以下信息，生成一条简洁友好的主动服务通知（不超过100字）：

用户关注：{description}
最新数据：{data_summary}
今天日期：{today}

要求：
- 用中文
- 直接说数据结论，如"中国平安今日收盘价 47.5 元，较昨日上涨 1.2%"
- 如数据获取失败，如实说明
- 不要客套语，直接给出信息
"""


class ProactiveServiceJob(BaseJob):
    """主动服务 Job：扫描用户 MEMORY，LLM 分析意图，工具获取数据，生成通知"""

    meta = JobMeta(
        job_id="proactive_service",
        cron="0 9 * * *",           # 每天早上 9 点触发
        max_concurrent_users=50,
        batch_size=500,
        user_timeout_secs=45.0,
    )

    def __init__(
        self,
        llm_factory: Callable[[], "BaseChatModel"],
        tool_registry: "ToolRegistry",
    ) -> None:
        self._get_llm = llm_factory
        self._tool_registry = tool_registry

    # ── 阶段1：轻量规则过滤 ────────────────────────────────────────────────

    async def should_process_user(self, user_id: str, memory: str) -> bool:
        """关键词扫描，不调用 LLM，< 1ms。"""
        return any(kw in memory for kw in _INTENT_KEYWORDS)

    # ── 阶段2：完整处理 ───────────────────────────────────────────────────

    async def process_user(self, user_id: str, memory: str) -> list[Notification] | None:
        today = datetime.now().strftime("%Y-%m-%d")

        # 1. LLM 提取意图
        intents = await self._extract_intents(memory, today)
        if not intents:
            return None

        # 2. 对每个意图：工具调用 + 生成通知
        notifications: list[Notification] = []
        for intent in intents:
            notification = await self._process_intent(user_id, intent, today)
            if notification:
                notifications.append(notification)

        return notifications if notifications else None

    # ── 私有：LLM 意图提取 ────────────────────────────────────────────────

    async def _extract_intents(self, memory: str, today: str) -> list[dict[str, Any]]:
        """调用 LLM 从 MEMORY.md 中提取主动服务意图。"""
        prompt = _INTENT_EXTRACT_PROMPT.format(memory=memory, today=today)
        try:
            llm = self._get_llm()
            response = await llm.ainvoke(prompt)
            raw = response.content
            if isinstance(raw, list):
                raw = " ".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in raw)
            data = self._parse_json(str(raw))
            if not data:
                return []
            return data.get("intents", [])
        except Exception as e:
            logger.warning("Intent extraction failed: %s", e)
            return []

    # ── 私有：处理单个意图 ────────────────────────────────────────────────

    async def _process_intent(
        self, user_id: str, intent: dict[str, Any], today: str
    ) -> Notification | None:
        intent_type = intent.get("type", "")
        symbol = intent.get("symbol", "")
        description = intent.get("description", symbol)

        # 工具调用获取实时数据
        data_summary = await self._fetch_data(intent_type, symbol)

        # 判断是否值得推送（数据获取失败时也推送，告知用户）
        notification_body = await self._generate_notification_text(description, data_summary, today)
        if not notification_body:
            return None

        return Notification(
            notification_id=str(uuid.uuid4()),
            user_id=user_id,
            job_id=self.meta.job_id,
            title=self._build_title(intent_type, symbol),
            body=notification_body,
            data={
                "intent_type": intent_type,
                "symbol": symbol,
                "raw_data": data_summary,
                "date": today,
            },
            priority="normal",
        )

    def _build_title(self, intent_type: str, symbol: str) -> str:
        if intent_type == "stock_alert":
            return f"股价播报 · {symbol}" if symbol else "股价播报"
        if intent_type == "remind":
            return "定期提醒"
        return "主动服务通知"

    # ── 私有：工具调用获取数据 ────────────────────────────────────────────

    async def _fetch_data(self, intent_type: str, symbol: str) -> str:
        """根据意图类型调用对应工具获取实时数据。

        工具调用直接走 ToolRegistry.get().execute()，不经过 AgentRunner。
        """
        if intent_type != "stock_alert" or not symbol:
            return f"关注内容：{symbol or '未知'}"

        # 尝试 security_info_search 工具（证券信息查询）
        tool = self._tool_registry.get("security_info_search")
        if tool is None:
            logger.debug("security_info_search tool not available")
            return f"股票 {symbol} 数据暂不可用"

        from ..types import ToolCall

        tool_call = ToolCall(
            id=str(uuid.uuid4()),
            name="security_info_search",
            arguments={"query": symbol},
        )
        try:
            result = await tool.execute(tool_call)
            if result.is_error:
                return f"股票 {symbol} 查询失败：{result.content}"
            # 将结果转为字符串摘要
            content = result.content
            if isinstance(content, (dict, list)):
                return json.dumps(content, ensure_ascii=False, indent=None)[:500]
            return str(content)[:500]
        except Exception as e:
            logger.warning("Tool call failed for %s: %s", symbol, e)
            return f"股票 {symbol} 数据获取异常"

    # ── 私有：LLM 生成通知文本 ────────────────────────────────────────────

    async def _generate_notification_text(
        self, description: str, data_summary: str, today: str
    ) -> str | None:
        """让 LLM 根据数据生成自然语言通知。"""
        prompt = _NOTIFY_PROMPT.format(
            description=description,
            data_summary=data_summary,
            today=today,
        )
        try:
            llm = self._get_llm()
            response = await llm.ainvoke(prompt)
            raw = response.content
            if isinstance(raw, list):
                raw = " ".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in raw)
            text = str(raw).strip()
            return text if text else None
        except Exception as e:
            logger.warning("Notification text generation failed: %s", e)
            return None

    # ── 工具方法 ──────────────────────────────────────────────────────────

    def _parse_json(self, raw: str) -> dict | None:
        """从 LLM 输出解析 JSON（兼容带 markdown 代码块的情况）。"""
        raw = raw.strip()
        # 去掉 ```json ... ``` 包裹
        if raw.startswith("```"):
            lines = raw.splitlines()
            raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            # 尝试提取第一个 {...}
            start = raw.find("{")
            end = raw.rfind("}")
            if start != -1 and end > start:
                try:
                    return json.loads(raw[start:end + 1])
                except json.JSONDecodeError:
                    pass
        return None
