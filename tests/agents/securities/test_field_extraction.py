"""Tests for field extraction utilities."""

import pytest

from ark_agentic.agents.securities.tools.field_extraction import (
    extract_fields,
    _get_by_path,
    extract_account_overview,
    ACCOUNT_OVERVIEW_FIELD_MAPPING,
    SERVICE_FIELD_MAPPINGS,
    extract_service_fields,
)


class TestGetByPath:
    """Test path-based value retrieval."""

    def test_get_simple_field(self):
        """Test extracting a simple field."""
        data = {"name": "John", "age": 30}
        assert _get_by_path(data, "name") == "John"

    def test_get_nested_field(self):
        """Test extracting a nested field with dot notation."""
        data = {
            "results": {
                "rmb": {
                    "totalAssetVal": "1000000.00"
                }
            }
        }
        result = _get_by_path(data, "results.rmb.totalAssetVal")
        assert result == "1000000.00"

    def test_get_deeply_nested_field(self):
        """Test extracting a deeply nested field."""
        data = {
            "results": {
                "rmb": {
                    "mktAssetsInfo": {
                        "totalMktVal": "500000.00"
                    }
                }
            }
        }
        result = _get_by_path(data, "results.rmb.mktAssetsInfo.totalMktVal")
        assert result == "500000.00"

    def test_get_missing_field(self):
        """Test extracting a missing field returns None."""
        data = {"name": "John"}
        assert _get_by_path(data, "missing.field") is None

    def test_get_from_none(self):
        """Test getting from None data."""
        assert _get_by_path(None, "path") is None


class TestExtractFields:
    """Test multiple field extraction."""

    def test_extract_multiple_fields(self):
        """Test extracting multiple fields at once."""
        data = {
            "results": {
                "rmb": {
                    "totalAssetVal": "1000000.00",
                    "cashGainAssetsInfo": {
                        "cashBalance": "500000.00"
                    }
                }
            }
        }
        
        mapping = {
            "total_assets": "results.rmb.totalAssetVal",
            "cash_balance": "results.rmb.cashGainAssetsInfo.cashBalance",
        }
        
        result = extract_fields(data, mapping)
        
        assert result["total_assets"] == "1000000.00"
        assert result["cash_balance"] == "500000.00"

    def test_extract_fields_with_missing(self):
        """Test extracting fields with some missing."""
        data = {
            "results": {
                "rmb": {
                    "totalAssetVal": "1000000.00",
                }
            }
        }
        
        mapping = {
            "total_assets": "results.rmb.totalAssetVal",
            "missing_field": "results.rmb.missing.value",
        }
        
        result = extract_fields(data, mapping)
        
        assert result["total_assets"] == "1000000.00"
        assert "missing_field" not in result


class TestExtractAccountOverview:
    """Test account overview extraction."""

    def test_extract_normal_account(self):
        """Test extracting normal account data."""
        data = {
            "status": 1,
            "results": {
                "accountType": "1",
                "rmb": {
                    "totalAssetVal": "390664059.82",
                    "cashGainAssetsInfo": {
                        "cashBalance": "1227455354.88"
                    },
                    "mktAssetsInfo": {
                        "totalMktVal": "267887813.40",
                        "totalMktProfitToday": "-54638.28",
                        "totalMktYieldToday": "-0.01"
                    },
                    "fundMktAssetsInfo": {
                        "fundMktVal": "1323481.54"
                    },
                    "rzrqAssetsInfo": None
                }
            }
        }
        
        result = extract_account_overview(data)
        
        assert result["total_assets"] == "390664059.82"
        assert result["cash_balance"] == "1227455354.88"
        assert result["stock_market_value"] == "267887813.40"
        assert result["fund_market_value"] == "1323481.54"
        assert result["today_profit"] == "-54638.28"
        assert result["today_return_rate"] == "-0.01"
        # net_assets should not be in result since rzrqAssetsInfo is None
        assert "net_assets" not in result

    def test_extract_margin_account(self):
        """Test extracting margin account data."""
        data = {
            "status": 1,
            "results": {
                "accountType": "2",
                "rmb": {
                    "totalAssetVal": "333678978.13",
                    "cashGainAssetsInfo": {
                        "cashBalance": "100815068.13"
                    },
                    "mktAssetsInfo": {
                        "totalMktVal": "233663910.00",
                        "totalMktProfitToday": "-1420880.00",
                        "totalMktYieldToday": "-0.42"
                    },
                    "fundMktAssetsInfo": None,
                    "rzrqAssetsInfo": {
                        "netWorth": "332733488.56",
                        "totalLiabilities": "945497.57",
                        "mainRatio": "35291.35"
                    }
                }
            }
        }
        
        result = extract_account_overview(data)
        
        assert result["total_assets"] == "333678978.13"
        assert result["cash_balance"] == "100815068.13"
        assert result["stock_market_value"] == "233663910.00"
        rzrq = result.get("rzrq_assets_info")
        assert isinstance(rzrq, dict)
        assert rzrq.get("netWorth") == "332733488.56"
        assert rzrq.get("totalLiabilities") == "945497.57"
        assert rzrq.get("mainRatio") == "35291.35"

    def test_extract_with_null_nested_object(self):
        """Test extraction when nested object is null."""
        data = {
            "status": 1,
            "results": {
                "accountType": "1",
                "rmb": {
                    "totalAssetVal": "1000000.00",
                    "fundMktAssetsInfo": None,
                    "rzrqAssetsInfo": None
                }
            }
        }
        
        result = extract_account_overview(data)
        
        assert result["total_assets"] == "1000000.00"
        assert "fund_market_value" not in result
        assert "net_assets" not in result


class TestFieldMappingConfiguration:
    """Test field mapping configuration."""

    def test_field_mapping_exists(self):
        """Test that field mapping is defined."""
        assert "total_assets" in ACCOUNT_OVERVIEW_FIELD_MAPPING
        assert "cash_balance" in ACCOUNT_OVERVIEW_FIELD_MAPPING
        assert "stock_market_value" in ACCOUNT_OVERVIEW_FIELD_MAPPING

    def test_field_mapping_paths(self):
        """Test field mapping paths are correct."""
        assert ACCOUNT_OVERVIEW_FIELD_MAPPING["total_assets"] == "results.rmb.totalAssetVal"
        assert ACCOUNT_OVERVIEW_FIELD_MAPPING["cash_balance"] == "results.rmb.cashGainAssetsInfo.cashBalance"
        assert ACCOUNT_OVERVIEW_FIELD_MAPPING["rzrq_assets_info"] == "results.rmb.rzrqAssetsInfo"

    def test_service_field_mappings_registered(self):
        """Test that service field mappings are registered."""
        assert "account_overview" in SERVICE_FIELD_MAPPINGS
        assert "cash_assets" in SERVICE_FIELD_MAPPINGS
        assert "etf_holdings" in SERVICE_FIELD_MAPPINGS
        assert "hksc_holdings" in SERVICE_FIELD_MAPPINGS


class TestExtractServiceFields:
    """Test service field extraction."""

    def test_extract_account_overview_service(self):
        """Test extracting account overview service fields."""
        data = {
            "results": {
                "rmb": {
                    "totalAssetVal": "1000000.00"
                }
            }
        }
        
        result = extract_service_fields("account_overview", data)
        assert result["total_assets"] == "1000000.00"

    def test_extract_unknown_service(self):
        """Test extracting unknown service returns original data."""
        data = {"some": "data"}
        result = extract_service_fields("unknown_service", data)
        assert result == data