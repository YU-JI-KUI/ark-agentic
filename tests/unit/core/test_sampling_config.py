"""Unit tests for SamplingConfig."""

from __future__ import annotations

import pytest

from ark_agentic.core.llm.sampling import SamplingConfig


class TestDefaults:
    def test_for_chat_defaults_match_financial_scenario(self) -> None:
        cfg = SamplingConfig.for_chat()
        assert cfg.temperature == 0.1
        assert cfg.top_p == 0.9
        assert cfg.top_k == 20
        assert cfg.repetition_penalty == 1.05
        assert cfg.presence_penalty == 0.6
        assert cfg.min_p == 0.0
        assert cfg.max_tokens == 4096
        assert cfg.seed is None
        assert cfg.enable_thinking is False

    def test_bare_constructor_equals_for_chat(self) -> None:
        assert SamplingConfig() == SamplingConfig.for_chat()


class TestPresets:
    def test_for_extraction_is_greedy_and_reproducible(self) -> None:
        cfg = SamplingConfig.for_extraction()
        assert cfg.temperature == 0.0
        assert cfg.top_p == 1.0
        assert cfg.top_k == 1
        assert cfg.repetition_penalty == 1.0
        assert cfg.presence_penalty == 0.0
        assert cfg.seed == 42
        assert cfg.max_tokens == 2048

    def test_for_summarization_balances_stability_and_fluency(self) -> None:
        cfg = SamplingConfig.for_summarization()
        assert cfg.temperature == 0.2
        assert cfg.top_p == 0.8
        assert cfg.top_k == 20
        assert cfg.repetition_penalty == 1.1
        assert cfg.presence_penalty == 0.0
        assert cfg.seed is None
        assert cfg.max_tokens == 1024


class TestOverrides:
    def test_for_chat_accepts_overrides(self) -> None:
        cfg = SamplingConfig.for_chat(temperature=0.5, max_tokens=8192)
        assert cfg.temperature == 0.5
        assert cfg.max_tokens == 8192
        assert cfg.top_p == 0.9

    def test_for_extraction_overrides_preserve_base_when_unspecified(self) -> None:
        cfg = SamplingConfig.for_extraction(max_tokens=4096)
        assert cfg.max_tokens == 4096
        assert cfg.temperature == 0.0
        assert cfg.seed == 42

    def test_for_summarization_overrides(self) -> None:
        cfg = SamplingConfig.for_summarization(temperature=0.0, seed=7)
        assert cfg.temperature == 0.0
        assert cfg.seed == 7
        assert cfg.repetition_penalty == 1.1

    def test_model_copy_works(self) -> None:
        base = SamplingConfig.for_chat()
        updated = base.model_copy(update={"temperature": 0.9, "seed": 123})
        assert updated.temperature == 0.9
        assert updated.seed == 123
        assert updated.top_p == base.top_p
        assert base.temperature == 0.1


class TestSerialization:
    def test_to_chat_openai_kwargs_shape(self) -> None:
        kwargs = SamplingConfig.for_chat().to_chat_openai_kwargs()
        assert set(kwargs.keys()) == {
            "temperature",
            "top_p",
            "presence_penalty",
            "max_tokens",
        }
        assert kwargs["temperature"] == 0.1
        assert kwargs["top_p"] == 0.9
        assert kwargs["presence_penalty"] == 0.6
        assert kwargs["max_tokens"] == 4096

    def test_to_extra_body_includes_vllm_extensions(self) -> None:
        body = SamplingConfig.for_chat().to_extra_body()
        assert body["top_k"] == 20
        assert body["repetition_penalty"] == 1.05
        assert body["min_p"] == 0.0
        assert body["chat_template_kwargs"] == {
            "enable_thinking": False,
            "thinking": False,
        }

    def test_seed_none_absent_from_extra_body(self) -> None:
        body = SamplingConfig.for_chat().to_extra_body()
        assert "seed" not in body

    def test_seed_present_for_extraction(self) -> None:
        body = SamplingConfig.for_extraction().to_extra_body()
        assert body["seed"] == 42

    def test_explicit_seed_in_overrides_writes_to_body(self) -> None:
        body = SamplingConfig.for_chat(seed=99).to_extra_body()
        assert body["seed"] == 99

    def test_enable_thinking_flag_propagates(self) -> None:
        body = SamplingConfig.for_chat(enable_thinking=True).to_extra_body()
        assert body["chat_template_kwargs"] == {
            "enable_thinking": True,
            "thinking": True,
        }


class TestValidation:
    @pytest.mark.parametrize("value", [-0.1, 2.1])
    def test_temperature_range_enforced(self, value: float) -> None:
        with pytest.raises(ValueError):
            SamplingConfig(temperature=value)

    @pytest.mark.parametrize("value", [-0.1, 1.1])
    def test_top_p_range_enforced(self, value: float) -> None:
        with pytest.raises(ValueError):
            SamplingConfig(top_p=value)

    def test_max_tokens_must_be_positive(self) -> None:
        with pytest.raises(ValueError):
            SamplingConfig(max_tokens=0)
