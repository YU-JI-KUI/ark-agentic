"""Tests for SessionEffect typed tool→session write channel."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ark_agentic.core.types import SessionEffect


def test_session_effect_activate_skill_validates() -> None:
    eff = SessionEffect.model_validate(
        {"op": "activate_skill", "skill_ids": ["s1", "s2"]}
    )
    assert eff.op == "activate_skill"
    assert eff.skill_ids == ["s1", "s2"]


def test_session_effect_skill_ids_default_empty_list() -> None:
    eff = SessionEffect.model_validate({"op": "activate_skill"})
    assert eff.skill_ids == []


def test_session_effect_unknown_op_raises() -> None:
    with pytest.raises(ValidationError):
        SessionEffect.model_validate({"op": "delete_session", "skill_ids": []})


def test_session_effect_skill_ids_must_be_list_of_str() -> None:
    with pytest.raises(ValidationError):
        SessionEffect.model_validate(
            {"op": "activate_skill", "skill_ids": [1, 2, 3]},
        )
