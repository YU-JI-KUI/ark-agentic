"""Tests for parameter mapping utilities."""

import os
import pytest

from ark_agentic.agents.securities.tools.param_mapping import (
    build_api_request,
    build_api_headers_with_validatedata,
    build_validatedata,
    validate_validatedata_fields,
    _get_by_path,
    _set_by_path,
    _get_context_value,
    ACCOUNT_OVERVIEW_PARAM_CONFIG,
    SERVICE_PARAM_CONFIGS,
    VALIDATEDATA_REQUIRED_FIELDS,
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


class TestGetContextValue:
    """Test context value retrieval with user: prefix support."""

    def test_get_with_user_prefix(self):
        """Test getting value with user: prefix (highest priority)."""
        context = {"user:token_id": "prefixed_value", "token_id": "bare_value"}
        assert _get_context_value(context, "token_id") == "prefixed_value"

    def test_get_with_bare_key(self):
        """Test getting value with bare key (fallback)."""
        context = {"token_id": "bare_value"}
        assert _get_context_value(context, "token_id") == "bare_value"

    def test_get_with_both_prefix_and_bare(self):
        """Test that user: prefix takes priority over bare key."""
        context = {"user:token_id": "prefixed", "token_id": "bare"}
        assert _get_context_value(context, "token_id") == "prefixed"

    def test_get_from_none_context(self):
        """Test getting from None context returns default."""
        assert _get_context_value(None, "key", "default") == "default"

    def test_get_missing_key_returns_default(self):
        """Test that missing key returns default value."""
        context = {"other_key": "value"}
        assert _get_context_value(context, "missing", "default") == "default"


class TestBuildValidatedata:
    """Test validatedata string building."""

    def test_build_validatedata_full_context(self):
        """Test building validatedata with all required fields."""
        context = {
            "user:channel": "REST",
            "user:usercode": "150573383",
            "user:userid": "12977997",
            "user:account": "3310123",
            "user:branchno": "3310",
            "user:loginflag": "3",
            "user:mobileNo": "137123123",
        }

        validatedata = build_validatedata(context, skip_on_mock=False)

        assert "channel=REST" in validatedata
        assert "usercode=150573383" in validatedata
        assert "userid=12977997" in validatedata
        assert "account=3310123" in validatedata
        assert "branchno=3310" in validatedata
        assert "loginflag=3" in validatedata
        assert "mobileNo=137123123" in validatedata

    def test_build_validatedata_with_bare_keys(self):
        """Test building validatedata with bare keys (no user: prefix)."""
        context = {
            "channel": "REST",
            "usercode": "150573383",
            "userid": "12977997",
            "account": "3310123",
            "branchno": "3310",
            "loginflag": "3",
            "mobileNo": "137123123",
        }

        validatedata = build_validatedata(context, skip_on_mock=False)

        assert "channel=REST" in validatedata
        assert "usercode=150573383" in validatedata

    def test_build_validatedata_mixed_prefix_and_bare(self):
        """Test that user: prefix takes priority when both exist."""
        context = {
            "user:channel": "PREFIXED",
            "channel": "BARE",
            "user:usercode": "150573383",
            "userid": "12977997",
            "account": "3310123",
            "branchno": "3310",
            "loginflag": "3",
            "mobileNo": "137123123",
        }

        validatedata = build_validatedata(context, skip_on_mock=False)

        assert "channel=PREFIXED" in validatedata

    def test_build_validatedata_missing_field_raises_error(self):
        """Test that missing required field raises ValueError."""
        context = {
            "channel": "REST",
            "usercode": "150573383",
            # Missing other required fields
        }

        with pytest.raises(ValueError, match="validatedata 缺少必需字段"):
            build_validatedata(context, skip_on_mock=False)

    def test_build_validatedata_empty_field_raises_error(self):
        """Test that empty required field raises ValueError."""
        context = {
            "channel": "REST",
            "usercode": "",  # Empty string
            "userid": "12977997",
            "account": "3310123",
            "branchno": "3310",
            "loginflag": "3",
            "mobileNo": "137123123",
        }

        with pytest.raises(ValueError, match="validatedata 缺少必需字段"):
            build_validatedata(context, skip_on_mock=False)

    def test_build_validatedata_mock_mode_returns_empty(self):
        """Test that mock mode returns empty string."""
        # Set mock environment variable
        os.environ["SECURITIES_SERVICE_MOCK"] = "true"

        try:
            context = {"channel": "REST"}  # Incomplete context
            validatedata = build_validatedata(context, skip_on_mock=True)
            assert validatedata == ""
        finally:
            # Clean up
            os.environ.pop("SECURITIES_SERVICE_MOCK", None)

    def test_build_validatedata_custom_fields(self):
        """Test building validatedata with custom required fields."""
        custom_fields = ["channel", "usercode"]
        context = {
            "channel": "REST",
            "usercode": "150573383",
            # Other fields missing but not in custom list
        }

        validatedata = build_validatedata(
            context, required_fields=custom_fields, skip_on_mock=False
        )

        assert "channel=REST" in validatedata
        assert "usercode=150573383" in validatedata


class TestValidateValidatedataFields:
    """Test validatedata field validation."""

    def test_validate_all_fields_present(self):
        """Test validation with all required fields present."""
        context = {
            "user:channel": "REST",
            "user:usercode": "150573383",
            "user:userid": "12977997",
            "user:account": "3310123",
            "user:branchno": "3310",
            "user:loginflag": "3",
            "user:mobileNo": "137123123",
        }

        missing = validate_validatedata_fields(
            context, required_fields=VALIDATEDATA_REQUIRED_FIELDS, skip_on_mock=False
        )

        assert missing == []

    def test_validate_missing_fields(self):
        """Test validation detects missing fields."""
        context = {
            "channel": "REST",
            # Missing other fields
        }

        missing = validate_validatedata_fields(
            context, required_fields=VALIDATEDATA_REQUIRED_FIELDS, skip_on_mock=False
        )

        assert len(missing) > 0
        assert "usercode" in missing
        assert "userid" in missing

    def test_validate_empty_fields(self):
        """Test validation detects empty fields."""
        context = {
            "channel": "",
            "usercode": "150573383",
            # Missing other fields
        }

        missing = validate_validatedata_fields(
            context, required_fields=VALIDATEDATA_REQUIRED_FIELDS, skip_on_mock=False
        )

        assert "channel" in missing  # Empty string counts as missing

    def test_validate_mock_mode_skip(self):
        """Test that mock mode skips validation."""
        os.environ["SECURITIES_SERVICE_MOCK"] = "true"

        try:
            context = {}  # Empty context
            missing = validate_validatedata_fields(
                context, required_fields=VALIDATEDATA_REQUIRED_FIELDS, skip_on_mock=True
            )

            # Mock mode should return empty list (no missing fields)
            assert missing == []
        finally:
            os.environ.pop("SECURITIES_SERVICE_MOCK", None)


class TestBuildApiHeadersWithValidatedata:
    """Test API headers building with validatedata support."""

    def test_build_headers_with_validatedata(self):
        """Test building headers with validatedata and signature."""
        header_config = {
            "validatedata": ("validatedata", "build"),
            "signature": ("context", "signature"),
        }

        context = {
            "channel": "REST",
            "usercode": "150573383",
            "userid": "12977997",
            "account": "3310123",
            "branchno": "3310",
            "loginflag": "3",
            "mobileNo": "137123123",
            "signature": "test_signature",
        }

        headers = build_api_headers_with_validatedata(header_config, context)

        assert "validatedata" in headers
        assert "signature" in headers
        assert headers["signature"] == "test_signature"
        assert "channel=REST" in headers["validatedata"]

    def test_build_headers_without_validatedata(self):
        """Test building headers without validatedata (only signature)."""
        header_config = {
            "signature": ("context", "signature"),
        }

        context = {"signature": "test_signature"}

        headers = build_api_headers_with_validatedata(header_config, context)

        assert "validatedata" not in headers
        assert headers["signature"] == "test_signature"

    def test_build_headers_missing_signature(self):
        """Test that missing signature results in no signature header."""
        header_config = {
            "signature": ("context", "signature"),
        }

        context = {}  # No signature

        headers = build_api_headers_with_validatedata(header_config, context)

        assert "signature" not in headers

    def test_build_headers_none_context(self):
        """Test building headers with None context."""
        header_config = {
            "validatedata": ("validatedata", "build"),
            "signature": ("context", "signature"),
        }

        headers = build_api_headers_with_validatedata(header_config, None)

        assert headers == {}