"""Tests for core.a2ui.preset_registry (PresetRegistry)."""

from ark_agentic.core.a2ui.blocks import A2UIOutput
from ark_agentic.core.a2ui.preset_registry import PresetRegistry


def _mock_extractor(context: dict, card_args: dict | None) -> A2UIOutput:
    data = dict(card_args or {})
    data["enriched"] = True
    return A2UIOutput(template_data=data, llm_digest="test")


def test_register_and_get():
    reg = PresetRegistry()
    reg.register("test_card", _mock_extractor)

    ext = reg.get("test_card")
    assert ext is not None
    output = ext({}, {"key": "val"})
    assert output.template_data["key"] == "val"
    assert output.template_data["enriched"] is True
    assert output.llm_digest == "test"


def test_get_unknown_returns_none():
    reg = PresetRegistry()
    assert reg.get("unknown") is None


def test_types_sorted():
    reg = PresetRegistry()
    reg.register("z_test", _mock_extractor)
    reg.register("a_test", _mock_extractor)

    types = reg.types
    assert "a_test" in types
    assert "z_test" in types
    assert types.index("a_test") < types.index("z_test")


def test_len_and_bool():
    reg = PresetRegistry()
    assert len(reg) == 0
    assert not reg

    reg.register("card", _mock_extractor)
    assert len(reg) == 1
    assert reg


def test_register_returns_self_for_chaining():
    reg = PresetRegistry()
    result = reg.register("a", _mock_extractor)
    assert result is reg
