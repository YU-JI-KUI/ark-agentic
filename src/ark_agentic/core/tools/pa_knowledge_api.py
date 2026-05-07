"""
PA 内部在线 RAG 知识库 API 工具

可选工具：不在任何 agent 中默认注册。使用方在 agent 创建后
通过 ``agent.tool_registry.register(...)`` 按需注册，支持同时注册多个
不同端点实例。

使用示例:
    from ark_agentic.core.tools import PAKnowledgeAPIConfig, create_pa_knowledge_api_tool

    agent = InsuranceAgent()
    agent.tool_registry.register(create_pa_knowledge_api_tool(PAKnowledgeAPIConfig(
        tool_name="search_product_faq",
        faq_url="https://pa-api.example/kn/knSearch",
        tenant_id="wfcz-yjdd",
        kn_ids=["3106"],
        app_secret="xxx",
        token_auth_url="https://pa-api.example/auth/token",
    )))
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any

import httpx

from .base import AgentTool, ToolParameter
from ..types import AgentToolResult, ToolCall

logger = logging.getLogger(__name__)


@dataclass
class PAKnowledgeAPIConfig:
    """PA 内部在线 RAG 知识库 API 配置。

    在调用方代码中直接构造，不通过 env var 驱动，
    以避免多端点场景下 env var 臃肿。

    Args:
        faq_url:          PA 知识检索 API 地址
        tenant_id:        租户 ID（对应 API 的 tenantId）
        kn_ids:           知识库 ID 列表
        tool_name:        LLM 可见的工具名称，同一 agent 注册多个实例时须不同
        top_n:            每个 query 最多返回条数
        faq_score_limit:  FAQ 相关性分数阈值
        rag_strategy:     检索策略（1 = 默认）
        app_secret:       动态 token 认证密钥（与 token_auth_url 配合使用）
        token_auth_url:   动态 token 获取地址
        static_auth_token: 静态 auth-token（与 app_secret 二选一）
    """

    faq_url: str
    tenant_id: str
    kn_ids: list[str]                    # 必需，无默认值（避免 mutable default）
    tool_name: str = "pa_knowledge_api"  # 多实例时给每个实例不同名称
    top_n: int = 5
    faq_score_limit: float = 0.84
    rag_strategy: int = 1
    app_secret: str | None = None
    token_auth_url: str | None = None
    static_auth_token: str | None = None


class PAKnowledgeAPITool(AgentTool):
    """PA 内部在线 RAG 知识库 API 工具

    - 并行检索多个 query 并融合去重结果
    - 支持动态 token（app_secret + token_auth_url）或静态 token
    - Token 带 55min TTL 缓存，asyncio.Lock 防并发重复刷新
    """

    # AgentTool 非 dataclass，parameters 必须用类级字面量（而非 field()）
    name = "pa_knowledge_api"
    description = "调用 PA 内部在线 RAG 知识库 API，并行检索多个 query 并融合结果"
    thinking_hint = "正在检索知识库…"
    parameters = [
        ToolParameter(
            name="queries",
            type="array",
            description="检索 query 列表，支持多个并行检索以提升召回率",
            required=True,
            items={"type": "string"},
        )
    ]

    def __init__(self, config: PAKnowledgeAPIConfig) -> None:
        self._config = config
        # 实例级 name 覆盖：支持同一 agent 注册多个不同端点实例
        self.name = config.tool_name
        self.description = f"调用 PA 内部在线 RAG 知识库 API [{config.tool_name}]，并行检索多个 query 并融合结果"
        # Token 缓存（静态 token 直接用，expire=inf）
        self._token: str | None = config.static_auth_token
        self._token_expire: float = float("inf") if config.static_auth_token else 0.0
        self._token_lock = asyncio.Lock()  # asyncio.Lock，非 threading.Lock

    # ---- Token 管理 ----

    async def _get_token(self) -> str:
        """Double-checked locking + TTL 缓存，避免并发重复刷新 token."""
        now = time.time()
        if self._token and now < self._token_expire:
            return self._token
        async with self._token_lock:
            if self._token and now < self._token_expire:
                return self._token
            cfg = self._config
            if cfg.app_secret and cfg.token_auth_url:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.post(
                        cfg.token_auth_url,
                        json={"appId": cfg.tenant_id, "appSecret": cfg.app_secret},
                    )
                    data = resp.json()
                    if "data" in data:
                        self._token = str(data["data"])
                        self._token_expire = now + 3300  # 55min（留 5min 冗余）
                    else:
                        raise ValueError(
                            f"[{self.name}] Token refresh failed: {data}"
                        )
            else:
                raise ValueError(
                    f"[{self.name}] Auth not configured: "
                    "provide app_secret+token_auth_url or static_auth_token"
                )
        return self._token  # type: ignore[return-value]

    # ---- Request 构建 ----

    def _build_body(self, query: str, session_id: str, request_id: str) -> dict[str, Any]:
        """显式 snake_case → camelCase 映射，与 PA API 契约对齐."""
        cfg = self._config
        return {
            "sessionId": session_id,
            "requestId": request_id,
            "tenantId": cfg.tenant_id,
            "content": query,
            "context": {
                "knIds": cfg.kn_ids,
                "ragStrategy": cfg.rag_strategy,
                "topN": cfg.top_n,
                "faqScoreLimit": cfg.faq_score_limit,
                "property": {},
            },
        }

    # ---- 执行 ----

    async def execute(
        self, tool_call: ToolCall, context: dict[str, Any] | None = None
    ) -> AgentToolResult:
        args = tool_call.arguments or {}
        raw = args.get("queries", [])
        # LLM 传单字符串时归一化为 list
        queries: list[str] = (
            [raw] if isinstance(raw, str)
            else raw if isinstance(raw, list)
            else []
        )
        if not queries:
            return AgentToolResult.json_result(
                tool_call.id, {"error": "queries is required", "results": []}
            )

        ctx = context or {}
        # runner 已注入 session_id；此处为安全兜底（修正 x-agent 原始 bug）
        session_id = str(ctx.get("session_id") or uuid.uuid4().hex)

        token = await self._get_token()
        headers = {"Content-Type": "application/json", "auth-token": token}

        async def _call(q: str) -> dict[str, Any] | BaseException:
            body = self._build_body(q, session_id, uuid.uuid4().hex)
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    r = await client.post(self._config.faq_url, json=body, headers=headers)
                    return r.json()
            except Exception as exc:
                return exc

        # return_exceptions=True：部分 query 失败时仍返回其余可用结果
        raw_results = await asyncio.gather(
            *[_call(q) for q in queries], return_exceptions=True
        )
        fused = _fuse_results(list(raw_results), tool_name=self.name)
        return AgentToolResult.json_result(
            tool_call.id, {"results": fused, "total": len(fused)}
        )


# ---- 模块级辅助函数（便于测试独立调用）----

def _fuse_results(results: list[Any], tool_name: str = "pa_knowledge_api") -> list[dict[str, Any]]:
    """合并多个 query 的检索结果，去重，过滤异常响应."""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for r in results:
        if isinstance(r, BaseException):
            logger.warning(f"[{tool_name}] query error: {r}")
            continue
        if not (isinstance(r, dict) and r.get("code") == "200" and "data" in r):
            continue
        for item in r["data"]:
            if "segContent" not in item:
                continue
            try:
                seg = json.loads(item["segContent"])
                entry: dict[str, Any] = {
                    "hitQuestion": seg["question"],
                    "answer": seg["answer"],
                }
            except Exception:
                entry = {"raw": item["segContent"]}
            key = json.dumps(entry, sort_keys=True, ensure_ascii=False)
            if key not in seen:
                seen.add(key)
                out.append(entry)
    return out


def create_pa_knowledge_api_tool(config: PAKnowledgeAPIConfig) -> PAKnowledgeAPITool:
    """工厂函数：从配置创建 PAKnowledgeAPITool 实例."""
    return PAKnowledgeAPITool(config)
