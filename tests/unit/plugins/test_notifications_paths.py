"""验证 services/notifications/paths.py 的环境变量解析。"""

from __future__ import annotations

from pathlib import Path

import pytest

from ark_agentic.plugins.notifications.paths import get_notifications_base_dir


def test_default_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NOTIFICATIONS_DIR", raising=False)
    assert get_notifications_base_dir() == Path("data/ark_notifications")


def test_env_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    custom = tmp_path / "custom_notifs"
    monkeypatch.setenv("NOTIFICATIONS_DIR", str(custom))
    assert get_notifications_base_dir() == custom


def test_reexported_from_package() -> None:
    """get_notifications_base_dir 应该可从 services.notifications 顶层导入。"""
    from ark_agentic.plugins.notifications import (
        get_notifications_base_dir as reexported,
    )
    assert reexported is get_notifications_base_dir
