from __future__ import annotations

import importlib
import sys
import types


def test_init_phoenix_skips_when_disabled(monkeypatch) -> None:
    monkeypatch.delenv("ENABLE_PHOENIX", raising=False)
    monkeypatch.delenv("PHOENIX_COLLECTOR_ENDPOINT", raising=False)
    monkeypatch.delenv("PHOENIX_PROJECT_NAME", raising=False)
    monkeypatch.delenv("PHOENIX_API_KEY", raising=False)
    monkeypatch.delenv("PHOENIX_CLIENT_HEADERS", raising=False)

    from ark_agentic.core.observability import phoenix

    module = importlib.reload(phoenix)
    assert module.init_phoenix() is None


def test_init_phoenix_registers_and_shutdowns(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _Provider:
        def __init__(self) -> None:
            self.shutdown_called = False

        def shutdown(self) -> None:
            self.shutdown_called = True

    provider = _Provider()

    def _register(**kwargs):
        captured.update(kwargs)
        return provider

    phoenix_pkg = types.ModuleType("phoenix")
    otel_mod = types.ModuleType("phoenix.otel")
    otel_mod.register = _register
    phoenix_pkg.otel = otel_mod

    monkeypatch.setitem(sys.modules, "phoenix", phoenix_pkg)
    monkeypatch.setitem(sys.modules, "phoenix.otel", otel_mod)
    monkeypatch.setenv("ENABLE_PHOENIX", "true")
    monkeypatch.setenv("PHOENIX_PROJECT_NAME", "ark-tests")
    monkeypatch.setenv("PHOENIX_COLLECTOR_ENDPOINT", "http://127.0.0.1:4317")

    from ark_agentic.core.observability import phoenix

    module = importlib.reload(phoenix)
    assert module.init_phoenix(service_name="ignored") is provider
    assert captured["project_name"] == "ark-tests"
    assert captured["endpoint"] == "http://127.0.0.1:4317"
    assert captured["auto_instrument"] is True
    assert captured["batch"] is True

    module.shutdown_phoenix()
    assert provider.shutdown_called is True
