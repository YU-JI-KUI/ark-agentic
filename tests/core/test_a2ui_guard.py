"""Tests for core.a2ui.guard — unified validation + data coverage + BlockDataError."""

import pytest

from ark_agentic.core.a2ui.guard import (
    BlockDataError,
    GuardResult,
    validate_data_coverage,
    validate_full_payload,
)
from ark_agentic.core.a2ui.blocks import get_block_builder


class TestValidateDataCoverage:
    def test_no_warnings_when_all_paths_present(self):
        payload = {
            "components": [
                {"id": "t1", "component": {"Text": {"text": {"path": "amount"}}}}
            ],
            "data": {"amount": "¥ 100"},
        }
        warnings = validate_data_coverage(payload)
        assert not warnings

    def test_warns_on_missing_path(self):
        payload = {
            "components": [
                {"id": "t1", "component": {"Text": {"text": {"path": "missing_key"}}}}
            ],
            "data": {"other": "val"},
        }
        warnings = validate_data_coverage(payload)
        assert len(warnings) == 1
        assert "missing_key" in warnings[0]

    def test_ignores_literal_string_bindings(self):
        payload = {
            "components": [
                {"id": "t1", "component": {"Text": {"text": {"literalString": "hello"}}}}
            ],
            "data": {},
        }
        warnings = validate_data_coverage(payload)
        assert not warnings

    def test_ignores_item_dot_paths(self):
        payload = {
            "components": [
                {"id": "t1", "component": {"Text": {"text": {"path": "item.label"}}}}
            ],
            "data": {},
        }
        warnings = validate_data_coverage(payload)
        assert not warnings


class TestValidateFullPayload:
    def _valid_payload(self) -> dict:
        return {
            "event": "beginRendering",
            "version": "1.0.0",
            "surfaceId": "test-1",
            "rootComponentId": "root",
            "components": [
                {"id": "root", "component": {"Column": {"children": {"explicitList": []}}}}
            ],
            "data": {},
        }

    def test_valid_payload_passes(self):
        result = validate_full_payload(self._valid_payload())
        assert result.ok
        assert not result.errors

    def test_event_contract_failure_strict(self):
        payload = self._valid_payload()
        del payload["rootComponentId"]
        result = validate_full_payload(payload, strict=True)
        assert not result.ok
        assert any("EVENT_CONTRACT" in e for e in result.errors)

    def test_event_contract_failure_lenient(self):
        payload = self._valid_payload()
        del payload["rootComponentId"]
        result = validate_full_payload(payload, strict=False)
        assert result.ok
        assert any("EVENT_CONTRACT" in w for w in result.warnings)

    def test_data_coverage_as_warnings(self):
        payload = self._valid_payload()
        payload["components"].append(
            {"id": "t1", "component": {"Text": {"text": {"path": "no_such_key"}}}}
        )
        result = validate_full_payload(payload)
        assert result.ok
        assert any("DATA_COVERAGE" in w for w in result.warnings)


class TestBlockDataError:
    def test_missing_keys_raises(self):
        builder = get_block_builder("InfoCard")
        with pytest.raises(BlockDataError) as exc_info:
            builder({}, lambda p: f"{p}-1")
        assert "title" in exc_info.value.missing_keys or "body" in exc_info.value.missing_keys
        assert exc_info.value.block_type == "InfoCard"

    def test_present_keys_passes(self):
        builder = get_block_builder("InfoCard")
        result = builder({"title": "T", "body": "B"}, lambda p: f"{p}-1")
        assert len(result) > 0

    def test_summary_header_requires_title_value(self):
        builder = get_block_builder("SummaryHeader")
        with pytest.raises(BlockDataError) as exc_info:
            builder({"title": "ok"}, lambda p: f"{p}-1")
        assert "value" in exc_info.value.missing_keys

    def test_divider_no_required_keys(self):
        builder = get_block_builder("Divider")
        result = builder({}, lambda p: f"{p}-1")
        assert len(result) > 0
