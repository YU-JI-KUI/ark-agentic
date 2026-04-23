from __future__ import annotations

import importlib
import sys
import types

import pytest


def _reload_observability():
    import ark_agentic.observability as observability
    import ark_agentic.observability.langfuse as langfuse
    import ark_agentic.observability.phoenix as phoenix
    import ark_agentic.observability.providers as providers

    importlib.reload(phoenix)
    importlib.reload(langfuse)
    importlib.reload(providers)
    return importlib.reload(observability)


def test_observability_disabled_ignores_legacy_enable_phoenix(monkeypatch) -> None:
    from ark_agentic.core.callbacks import RunnerCallbacks

    monkeypatch.delenv("ENABLE_OBSERVABILITY", raising=False)
    monkeypatch.delenv("OBSERVABILITY_PROVIDER", raising=False)
    monkeypatch.setenv("ENABLE_PHOENIX", "true")

    observability = _reload_observability()

    external = RunnerCallbacks()
    callbacks = observability.build_observability_callbacks(
        agent_id="insurance",
        agent_name="测试助手",
        callbacks=external,
    )

    assert observability.observability_enabled() is False
    assert callbacks is external


def test_observability_provider_selection_is_case_insensitive(monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_OBSERVABILITY", "true")
    monkeypatch.setenv("OBSERVABILITY_PROVIDER", "Langfuse")

    observability = _reload_observability()

    assert observability.selected_observability_provider() == "langfuse"


def test_build_observability_callbacks_wraps_external_callbacks_for_selected_provider(
    monkeypatch,
) -> None:
    from ark_agentic.core.callbacks import RunnerCallbacks

    monkeypatch.setenv("ENABLE_OBSERVABILITY", "true")
    monkeypatch.setenv("OBSERVABILITY_PROVIDER", "Langfuse")

    observability = _reload_observability()

    external_before = object()
    external_after = object()
    external_retry = object()
    external = RunnerCallbacks(
        before_agent=[external_before],
        after_agent=[external_after],
        before_loop_end=[external_retry],
    )

    callbacks = observability.build_observability_callbacks(
        agent_id="insurance",
        agent_name="测试助手",
        callbacks=external,
    )

    assert len(callbacks.before_agent) == 2
    assert callbacks.before_agent[1] is external_before
    assert callbacks.after_agent[0] is external_after
    assert len(callbacks.after_agent) == 2
    assert callbacks.before_loop_end == [external_retry]


def test_init_observability_initializes_selected_phoenix_provider(monkeypatch) -> None:
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
    monkeypatch.setenv("ENABLE_OBSERVABILITY", "true")
    monkeypatch.setenv("OBSERVABILITY_PROVIDER", "Phoenix")
    monkeypatch.setenv("PHOENIX_PROJECT_NAME", "ark-tests")
    monkeypatch.setenv("PHOENIX_COLLECTOR_ENDPOINT", "http://127.0.0.1:4317")

    observability = _reload_observability()

    assert observability.init_observability(service_name="ignored") is provider
    assert captured["project_name"] == "ark-tests"
    assert captured["endpoint"] == "http://127.0.0.1:4317"
    assert captured["auto_instrument"] is True
    assert captured["batch"] is True

    observability.shutdown_observability()
    assert provider.shutdown_called is True


def test_init_observability_initializes_selected_langfuse_provider(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _Client:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)
            self.shutdown_called = False

        def shutdown(self) -> None:
            self.shutdown_called = True

    client_holder: dict[str, _Client] = {}

    def _langfuse_ctor(**kwargs):
        client = _Client(**kwargs)
        client_holder["client"] = client
        return client

    langfuse_mod = types.ModuleType("langfuse")
    langfuse_mod.Langfuse = _langfuse_ctor
    langfuse_mod.get_client = lambda: client_holder["client"]

    monkeypatch.setitem(sys.modules, "langfuse", langfuse_mod)
    monkeypatch.setenv("ENABLE_OBSERVABILITY", "true")
    monkeypatch.setenv("OBSERVABILITY_PROVIDER", "Langfuse")

    observability = _reload_observability()

    client = observability.init_observability(service_name="ark-agentic-api")

    assert client is client_holder["client"]
    assert callable(captured["should_export_span"])

    observability.shutdown_observability()
    assert client_holder["client"].shutdown_called is True


def test_unknown_observability_provider_raises_clear_error(monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_OBSERVABILITY", "true")
    monkeypatch.setenv("OBSERVABILITY_PROVIDER", "UnknownVendor")

    observability = _reload_observability()

    with pytest.raises(ValueError, match="Unsupported observability provider"):
        observability.init_observability()
