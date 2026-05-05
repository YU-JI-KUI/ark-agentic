"""静态前端渲染契约测试。

用于防止 securities 卡片渲染字段错配和重复函数定义回归。
"""

from __future__ import annotations

from pathlib import Path


INDEX_HTML = (
    Path(__file__).resolve().parents[2]
    / "src" / "ark_agentic" / "portal" / "static" / "index.html"
)


def _read_index_html() -> str:
    return INDEX_HTML.read_text(encoding="utf-8")


def test_holdings_renderer_supports_backend_field_aliases() -> None:
    """持仓渲染应兼容后端字段 code/name 与 security_code/security_name。"""
    content = _read_index_html()
    assert "h.security_code || h.code" in content
    assert "h.security_name || h.name" in content


def test_account_overview_uses_today_return_rate() -> None:
    """账户总览渲染应优先使用 today_return_rate。"""
    content = _read_index_html()
    assert "today_return_rate" in content


def test_template_renderer_functions_are_not_duplicated() -> None:
    """模板渲染函数应只定义一次，避免后定义覆盖前定义。"""
    content = _read_index_html()

    assert content.count("function formatNumber(num)") == 1
    assert content.count("function toNum(v)") == 1
    assert content.count("function renderAccountOverviewCard(data)") == 1
    assert content.count("function renderHoldingsListCard(template)") == 1
    assert content.count("function renderCashAssetsCard(data)") == 1
    assert content.count("function renderSecurityDetailCard(data)") == 1
    assert content.count("function renderGenericCard(template)") == 1
