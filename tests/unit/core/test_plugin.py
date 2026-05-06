"""Plugin / Lifecycle Protocol contract tests."""

from __future__ import annotations

from ark_agentic.core.protocol.lifecycle import BaseLifecycle, Lifecycle
from ark_agentic.core.protocol.plugin import BasePlugin, Plugin


def test_base_plugin_satisfies_plugin_protocol() -> None:
    class P(BasePlugin):
        name = "x"

    assert isinstance(P(), Plugin)
    # Plugin extends Lifecycle, so it must also satisfy that.
    assert isinstance(P(), Lifecycle)


def test_base_lifecycle_satisfies_lifecycle_protocol() -> None:
    class L(BaseLifecycle):
        name = "x"

    assert isinstance(L(), Lifecycle)


def test_defaults_are_no_ops() -> None:
    class P(BasePlugin):
        name = "x"

    p = P()
    assert p.is_enabled() is True


async def test_init_default_is_no_op() -> None:
    class P(BasePlugin):
        name = "x"

    assert await P().init() is None


async def test_start_default_returns_none() -> None:
    class P(BasePlugin):
        name = "x"

    assert await P().start(ctx=object()) is None


async def test_stop_default_is_no_op() -> None:
    class P(BasePlugin):
        name = "x"

    assert await P().stop() is None


def test_install_routes_default_is_no_op() -> None:
    class P(BasePlugin):
        name = "x"

    # Doesn't matter what we pass — default ignores it.
    assert P().install_routes(app=object()) is None


def test_subclass_can_override_only_what_it_needs() -> None:
    routes_calls: list = []

    class WithRoutes(BasePlugin):
        name = "routes_only"

        def install_routes(self, app):
            routes_calls.append(app)

    p = WithRoutes()
    assert isinstance(p, Plugin)
    p.install_routes(app="fake_app")
    assert routes_calls == ["fake_app"]


def test_disabled_plugin_reports_false() -> None:
    class Disabled(BasePlugin):
        name = "off"

        def is_enabled(self) -> bool:
            return False

    assert Disabled().is_enabled() is False


async def test_start_stop_pair_runs_in_sequence() -> None:
    """Plugins that produce a runtime context return it from ``start``;
    ``stop`` is called by the host on shutdown — symmetric with start."""
    events: list[str] = []

    class Stateful(BasePlugin):
        name = "s"

        async def start(self, ctx):
            events.append("start")
            return {"started": True}

        async def stop(self):
            events.append("stop")

    p = Stateful()
    value = await p.start(ctx=None)
    assert value == {"started": True}
    assert events == ["start"]

    await p.stop()
    assert events == ["start", "stop"]
