"""Mock loader + service adapter checks (replaces script-style test_phase1)."""

from __future__ import annotations

import pytest

from ark_agentic.agents.securities.tools.service import create_service_adapter, get_mock_loader


@pytest.mark.slow
def test_mock_loader_scenarios_and_security_detail() -> None:
    loader = get_mock_loader()
    normal = loader.load("account_overview", "normal_user")
    assert normal.get("results", {}).get("rmb", {}).get("totalAssetVal")
    margin = loader.load("account_overview", "margin_user")
    assert margin.get("results", {}).get("accountType") == "2"
    assert margin.get("results", {}).get("rmb", {}).get("rzrqAssetsInfo", {}).get("mainRatio")
    etf = loader.load("etf_holdings", "default")
    assert isinstance(etf.get("results", {}).get("stockList", []), list)
    detail = loader.load("security_detail", security_code="510300")
    assert detail.get("data", {}).get("securityName")
    scenarios = loader.list_scenarios("account_overview")
    assert "normal_user" in scenarios


@pytest.mark.asyncio
@pytest.mark.slow
async def test_service_adapter_mock_account_and_etf(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SECURITIES_SERVICE_MOCK", "true")
    acc = create_service_adapter("account_overview", context={"mock_mode": True})
    try:
        d1 = await acc.call(account_type="normal", user_id="U001")
        assert d1.get("total_assets")
        d2 = await acc.call(account_type="margin", user_id="U001")
        assert d2.get("rzrq_assets_info", {}).get("mainRatio")
    finally:
        await acc.close()

    etf = create_service_adapter("etf_holdings", context={"mock_mode": True})
    try:
        d3 = await etf.call(account_type="normal", user_id="U001")
        assert isinstance(d3.get("stock_list", []), list)
    finally:
        await etf.close()
