"""
PA-JT LLM：科技网关（RSA + HMAC 签名）Transport + ChatOpenAI 构建。

Header 与 Body 注入全部在本模块的 Transport 内完成。
"""

from __future__ import annotations

import base64
import binascii
import hmac
import json as _json
import logging
import time
import uuid
from typing import Any, TYPE_CHECKING
from urllib.parse import urlencode

import httpx

if TYPE_CHECKING:
    from langchain_core.language_models.chat_models import BaseChatModel
    from .factory import PAModelConfig

logger = logging.getLogger(__name__)

# ---- 可选依赖：pycryptodome ----
try:
    from Crypto.Hash import SHA256
    from Crypto.PublicKey import RSA
    from Crypto.Signature import PKCS1_v1_5

    _HAS_CRYPTO = True
except ImportError:
    _HAS_CRYPTO = False


def _require_crypto() -> None:
    if not _HAS_CRYPTO:
        raise ImportError(
            "pycryptodome is required for PA-JT gateway RSA signing. "
            "Install with: uv add 'ark-agentic[pa-jt]' or uv add pycryptodome"
        )


def rsa_sign(rsa_private_key_hex: str, request_time: str) -> str:
    """RSA-SHA256 签名（科技网关平台鉴权）。"""
    _require_crypto()
    binary_key = binascii.a2b_hex(rsa_private_key_hex)
    private_key = RSA.import_key(binary_key)
    h = SHA256.new(request_time.encode("utf-8"))
    signer = PKCS1_v1_5.new(private_key)
    return signer.sign(h).hex().upper()


def hmac_sign(app_key: str, app_secret: str, request_time: str) -> str:
    """HMAC-SHA1 签名（GPT 平台鉴权）。"""
    params = {
        "openApiRequestTime": request_time,
        "appKey": app_key,
        "appSecret": app_secret,
    }
    query_string = urlencode(params).lower()
    digest = hmac.new(
        app_secret.encode("utf-8"),
        query_string.encode("utf-8"),
        "sha1",
    ).digest()
    return base64.b64encode(digest).decode("utf-8")


def _merge_body(content: bytes, fields: dict[str, Any]) -> bytes:
    """将 fields 合并进 JSON body；已存在的 key 不覆盖。"""
    if not content:
        return _json.dumps(fields).encode()
    try:
        body = _json.loads(content)
    except (ValueError, _json.JSONDecodeError):
        return content
    injected = {k: v for k, v in fields.items() if k not in body}
    if not injected:
        return content
    body.update(injected)
    return _json.dumps(body).encode()


def _rebuild_request(
    request: httpx.Request,
    extra_headers: dict[str, str],
    new_content: bytes,
) -> httpx.Request:
    """基于原请求构造新 Request，合并 headers 并替换 body。"""
    merged = dict(request.headers)
    merged.update(extra_headers)
    return httpx.Request(
        method=request.method,
        url=request.url,
        headers=merged,
        content=new_content,
        extensions=request.extensions,
    )


# ============ JT Transport ============


class PinganEAGWHeaderAsyncTransport(httpx.AsyncBaseTransport):
    """httpx 异步 Transport：为 PA-JT 请求注入鉴权 Header 与 PA Body 字段。"""

    def __init__(
        self,
        *,
        base_transport: httpx.AsyncBaseTransport | None = None,
        api_code: str = "",
        gateway_credential: str = "",
        gateway_key: str = "",
        app_key: str = "",
        app_secret: str = "",
        scene_id: str = "",
        enable_thinking: bool = False,
        extra_body: dict[str, Any] | None = None,
    ) -> None:
        self._transport = base_transport or httpx.AsyncHTTPTransport(retries=3)
        self._api_code = api_code
        self._gateway_credential = gateway_credential
        self._gateway_key = gateway_key
        self._app_key = app_key
        self._app_secret = app_secret
        self._scene_id = scene_id
        self._enable_thinking = enable_thinking
        self._extra_body = extra_body or {}

    def _build_auth_headers(self, request_id: str, request_time: str) -> dict[str, str]:
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "request_id": request_id,
            "scene_id": self._scene_id,
        }
        if self._gateway_credential and self._gateway_key:
            headers["openAPICode"] = self._api_code
            headers["openAPICredential"] = self._gateway_credential
            headers["openAPIRequestTime"] = request_time
            headers["openAPISignature"] = rsa_sign(self._gateway_key, request_time)
        if self._app_key and self._app_secret:
            headers["gpt_app_key"] = self._app_key
            headers["gpt_signature"] = hmac_sign(
                self._app_key, self._app_secret, request_time
            )
        return headers

    def _build_body_fields(self, request_id: str) -> dict[str, Any]:
        defaults: dict[str, Any] = {
            "request_id": request_id,
            "scene_id": self._scene_id,
            "seed": 42,
            "chat_template_kwargs": {
                "enable_thinking": self._enable_thinking,
                "thinking": self._enable_thinking,
            },
        }
        return {**defaults, **self._extra_body}

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        request_id = uuid.uuid4().hex
        request_time = str(int(time.time() * 1000))
        auth_headers = self._build_auth_headers(request_id, request_time)
        body_fields = self._build_body_fields(request_id)
        new_content = _merge_body(request.content, body_fields)
        new_request = _rebuild_request(request, auth_headers, new_content)
        return await self._transport.handle_async_request(new_request)


# ============ Builder ============


def create_pa_jt_llm(
    config: "PAModelConfig",
    *,
    temperature: float,
    max_tokens: int,
    streaming: bool,
    enable_thinking: bool = False,
    extra_body_override: dict[str, Any] | None = None,
) -> "BaseChatModel":
    """构建 PA-JT 系列 ChatOpenAI。Raises ImportError 若 pycryptodome 未安装。"""
    from langchain_openai import ChatOpenAI

    transport = PinganEAGWHeaderAsyncTransport(
        base_transport=httpx.AsyncHTTPTransport(retries=3),
        api_code=config.open_api_code,
        gateway_credential=config.open_api_credential,
        gateway_key=config.rsa_private_key,
        app_key=config.gpt_app_key,
        app_secret=config.gpt_app_secret,
        scene_id=config.scene_id,
        enable_thinking=enable_thinking,
        extra_body=extra_body_override,
    )
    http_client = httpx.AsyncClient(transport=transport)
    logger.info(f"PA-JT transport enabled for {config.model_name}")

    return ChatOpenAI(
        base_url=config.base_url,
        api_key="EMPTY",
        model=config.model_name,
        temperature=temperature,
        max_tokens=max_tokens,
        streaming=streaming,
        http_async_client=http_client,
    )
