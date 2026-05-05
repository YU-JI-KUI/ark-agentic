"""Storage mode selection — DB_TYPE env parsing + helpers."""

from __future__ import annotations

import pytest

from ark_agentic.core.storage import mode


def test_current_defaults_to_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DB_TYPE", raising=False)

    assert mode.current() == "file"


def test_current_resolves_sqlite(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DB_TYPE", "sqlite")

    assert mode.current() == "sqlite"


def test_current_unknown_value_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DB_TYPE", "postgres")

    with pytest.raises(ValueError, match="Unsupported DB_TYPE"):
        mode.current()


def test_is_database_false_for_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DB_TYPE", raising=False)

    assert mode.is_database() is False


def test_is_database_true_for_sqlite(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DB_TYPE", "sqlite")

    assert mode.is_database() is True
