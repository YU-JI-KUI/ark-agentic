"""Plugin Protocol contract tests."""

from __future__ import annotations

from ark_agentic.core.plugin import BasePlugin, Plugin


def test_base_plugin_satisfies_protocol() -> None:
    """A naked BasePlugin (with name) must satisfy the runtime-checkable
    Protocol — no overrides required."""

    class P(BasePlugin):
        name = "x"

    assert isinstance(P(), Plugin)


def test_base_plugin_defaults_are_no_ops() -> None:
    class P(BasePlugin):
        name = "x"

    p = P()
    assert p.is_enabled() is True


async def test_base_plugin_init_schema_is_no_op() -> None:
    class P(BasePlugin):
        name = "x"

    assert await P().init_schema() is None


async def test_base_plugin_lifespan_yields_none() -> None:
    class P(BasePlugin):
        name = "x"

    async with P().lifespan(app_ctx=object()) as value:
        assert value is None


def test_subclass_can_override_only_what_it_needs() -> None:
    """A plugin overriding only ``install_routes`` should still satisfy
    the Protocol via the base class' default for the rest."""

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


async def test_lifespan_can_yield_a_value_and_run_cleanup() -> None:
    """Plugins that produce a runtime context yield it from ``lifespan``;
    teardown after the ``yield`` runs on shutdown."""
    teardown_ran: list = []

    class Stateful(BasePlugin):
        name = "s"

        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def lifespan(self, app_ctx):
            try:
                yield {"started": True}
            finally:
                teardown_ran.append(True)

    p = Stateful()
    async with p.lifespan(app_ctx=None) as ctx:
        assert ctx == {"started": True}

    assert teardown_ran == [True]
