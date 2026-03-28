"""Tests for core.a2ui.lean_registry."""

from ark_agentic.core.a2ui.lean_registry import (
    build_lean_payload,
    register_lean_card,
    list_lean_types,
    _LEAN_REGISTRY,
)


def test_register_and_build():
    register_lean_card("test_card", lambda d: {**d, "enriched": True})
    try:
        payload = build_lean_payload("test_card", {"key": "val"})
        assert payload["template_type"] == "test_card"
        assert payload["data"]["key"] == "val"
        assert payload["data"]["enriched"] is True
    finally:
        _LEAN_REGISTRY.pop("test_card", None)


def test_build_unknown_type_passthrough():
    payload = build_lean_payload("unknown_type", {"a": 1})
    assert payload["template_type"] == "unknown_type"
    assert payload["data"]["a"] == 1


def test_list_lean_types():
    register_lean_card("z_test", lambda d: d)
    register_lean_card("a_test", lambda d: d)
    try:
        types = list_lean_types()
        assert "a_test" in types
        assert "z_test" in types
        assert types.index("a_test") < types.index("z_test")
    finally:
        _LEAN_REGISTRY.pop("z_test", None)
        _LEAN_REGISTRY.pop("a_test", None)
