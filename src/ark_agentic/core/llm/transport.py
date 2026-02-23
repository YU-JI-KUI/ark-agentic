"""
PA 网关 Transport

基于 httpx.AsyncBaseTransport，在每个请求前注入平安网关鉴权 Header。
支持 RSA 签名 (JT/SX 科技网关) + HMAC 签名 (GPT 平台)。

迁移自 x-agent: src/utils/pingan_eagw_transport_header.py
"""

from __future__ import annotations

import base64
import binascii
import hmac
import logging
import time
import uuid
from urllib.parse import urlencode

import httpx

logger = logging.getLogger(__name__)

# ---- 可选依赖：pycryptodome ----
# PA-JT 网关需要 RSA 签名，如果不用 JT 网关可不安装。

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


# ============ 签名工具函数 ============


def rsa_sign(rsa_private_key_hex: str, request_time: str) -> str:
    """RSA-SHA256 签名（科技网关平台鉴权）。

    Args:
        rsa_private_key_hex: RSA 私钥（十六进制字符串）
        request_time: 毫秒时间戳字符串

    Returns:
        大写十六进制签名
    """
    _require_crypto()
    binary_key = binascii.a2b_hex(rsa_private_key_hex)
    private_key = RSA.import_key(binary_key)
    h = SHA256.new(request_time.encode("utf-8"))
    signer = PKCS1_v1_5.new(private_key)
    return signer.sign(h).hex().upper()


def hmac_sign(app_key: str, app_secret: str, request_time: str) -> str:
    """HMAC-SHA1 签名（GPT 平台鉴权）。

    Args:
        app_key: 应用 Key
        app_secret: 应用 Secret
        request_time: 毫秒时间戳字符串

    Returns:
        Base64 编码签名
    """
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


# ============ Transport ============


class PinganEAGWHeaderAsyncTransport(httpx.AsyncBaseTransport):
    """httpx 异步 Transport 装饰器：为每个请求注入平安网关鉴权 Header。

    用法::

        transport = PinganEAGWHeaderAsyncTransport(
            base_transport=httpx.AsyncHTTPTransport(retries=3),
            api_code="API035059",
            gateway_credential="...",
            gateway_key="...",      # RSA 私钥 hex
            app_key="...",
            app_secret="...",
            scene_id="...",
        )
        client = httpx.AsyncClient(transport=transport)
    """

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
    ) -> None:
        self._transport = base_transport or httpx.AsyncHTTPTransport(retries=3)
        self._api_code = api_code
        self._gateway_credential = gateway_credential
        self._gateway_key = gateway_key
        self._app_key = app_key
        self._app_secret = app_secret
        self._scene_id = scene_id

    def _build_auth_headers(self) -> dict[str, str]:
        """构建一次性鉴权 headers（每次请求调用，时间戳实时生成）。"""
        request_id = uuid.uuid4().hex
        request_time = str(int(time.time() * 1000))

        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "request_id": request_id,
            "scene_id": self._scene_id,
        }

        # 科技网关 RSA 签名
        if self._gateway_credential and self._gateway_key:
            headers["openAPICode"] = self._api_code
            headers["openAPICredential"] = self._gateway_credential
            headers["openAPIRequestTime"] = request_time
            headers["openAPISignature"] = rsa_sign(self._gateway_key, request_time)

        # GPT 平台 HMAC 签名
        if self._app_key and self._app_secret:
            headers["gpt_app_key"] = self._app_key
            headers["gpt_signature"] = hmac_sign(
                self._app_key, self._app_secret, request_time
            )

        return headers

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        """在底层 transport 处理前注入鉴权 headers。"""
        auth_headers = self._build_auth_headers()
        request.headers.update(auth_headers)
        return await self._transport.handle_async_request(request)
