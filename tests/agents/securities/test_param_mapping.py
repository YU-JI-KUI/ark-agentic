"""Tests for parameter mapping utilities."""

import pytest

from ark_agentic.agents.securities.tools.param_mapping import (
    build_api_request,
    _get_by_path,
    _set_by_path,
    ACCOUNT_OVERVIEW_PARAM_CONFIG,
    SERVICE_PARAM_CONFIGS,
)


class TestGetByPath:
    """Test path-based value retrieval."""

    def test_get_simple_path(self):
        """Test getting a simple path."""
        data = {"name": "John", "age": 30}
        assert _get_by_path(data, "name") == "John"
        assert _get_by_path(data, "age") == 30

    def test_get_nested_path(self):
        """Test getting a nested path."""
        data = {
            "user": {
                "profile": {
                    "name": "John"
                }
            }
        }
        assert _get_by_path(data, "user.profile.name") == "John"

    def test_get_missing_path(self):
        """Test getting a missing path."""
        data = {"name": "John"}
        assert _get_by_path(data, "missing") is None
        assert _get_by_path(data, "missing.path") is None

    def test_get_from_none(self):
        """Test getting from None data."""
        assert _get_by_path(None, "path") is None


class TestSetByPath:
    """Test path-based value setting."""

    def test_set_simple_path(self):
        """Test setting a simple path."""
        data = {}
        _set_by_path(data, "name", "John")
        assert data["name"] == "John"

    def test_set_nested_path(self):
        """Test setting a nested path."""
        data = {}
        _set_by_path(data, "body.accountType", "1")
        assert data == {"body": {"accountType": "1"}}

    def test_set_deeply_nested_path(self):
        """Test setting a deeply nested path."""
        data = {}
        _set_by_path(data, "a.b.c.d", "value")
        assert data == {"a": {"b": {"c": {"d": "value"}}}}


class TestBuildApiRequest:
    """Test API request building."""

    def test_build_account_overview_request_normal(self):
        """Test building request for normal account (flat context)."""
        # 扁平 context 结构
        context = {
            "token_id": "test_token_123",
            "account_type": "normal",
            "user_id": "U001",
        }
        
        request = build_api_request(ACCOUNT_OVERVIEW_PARAM_CONFIG, context)
        
        assert request["channel"] == "native"
        assert request["appName"] == "AYLCAPP"
        assert request["tokenId"] == "test_token_123"
        assert request["body"]["accountType"] == "1"

    def test_build_account_overview_request_margin(self):
        """Test building request for margin account (flat context)."""
        # 扁平 context 结构
        context = {
            "token_id": "test_token_456",
            "account_type": "margin",
            "user_id": "U001",
        }
        
        request = build_api_request(ACCOUNT_OVERVIEW_PARAM_CONFIG, context)
        
        assert request["channel"] == "native"
        assert request["appName"] == "AYLCAPP"
        assert request["tokenId"] == "test_token_456"
        assert request["body"]["accountType"] == "2"

    def test_build_request_missing_account_type(self):
        """Test building request with missing account_type (flat context)."""
        context = {
            "token_id": "test_token_123",
        }
        
        request = build_api_request(ACCOUNT_OVERVIEW_PARAM_CONFIG, context)
        
        assert request["tokenId"] == "test_token_123"
        # When account_type is None, transform(None) returns None, so body.accountType won't be set
        assert request.get("body", {}).get("accountType") is None

    def test_build_request_static_values(self):
        """Test that static values are correctly set."""
        config = {
            "channel": ("static", "native"),
            "appName": ("static", "AYLCAPP"),
        }
        
        context = {}
        request = build_api_request(config, context)
        
        assert request["channel"] == "native"
        assert request["appName"] == "AYLCAPP"

    def test_build_request_context_values(self):
        """Test that context values are correctly retrieved (flat context)."""
        config = {
            "tokenId": ("context", "token_id"),
        }
        
        context = {"token_id": "my_token"}
        request = build_api_request(config, context)
        
        assert request["tokenId"] == "my_token"

    def test_build_request_transform_values(self):
        """Test that transform values are correctly applied (flat context)."""
        config = {
            "accountType": ("transform", "type", lambda x: "2" if x == "margin" else "1"),
        }
        
        context_normal = {"type": "normal"}
        request_normal = build_api_request(config, context_normal)
        assert request_normal["accountType"] == "1"
        
        context_margin = {"type": "margin"}
        request_margin = build_api_request(config, context_margin)
        assert request_margin["accountType"] == "2"


class TestServiceParamConfigs:
    """Test service parameter configurations."""

    def test_account_overview_config_exists(self):
        """Test that account_overview config exists."""
        assert "account_overview" in SERVICE_PARAM_CONFIGS

    def test_account_overview_config_has_required_fields(self):
        """Test account_overview config has required fields."""
        config = SERVICE_PARAM_CONFIGS["account_overview"]
        
        assert "channel" in config
        assert "appName" in config
        assert "tokenId" in config
        assert "body.accountType" in config