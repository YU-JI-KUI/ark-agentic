"""Bootstrap orchestrator tests.

Validates the lifecycle phases (``init_all`` / ``start_all`` /
``stop_all``) and that the ``lifespan`` context manager runs them in the
right order. Exercised directly against the canonical PLUGINS list to
confirm schema init succeeds in both DB modes.
"""

from __future__ import annotations

from typing import Any

from ark_agentic.core.bootstrap import Bootstrap
from ark_agentic.core.db.engine import reset_engine_cache
from ark_agentic.core.lifecycle import BaseLifecycle


async def test_bootstrap_runs_default_plugins_in_file_mode(monkeypatch):
    from ark_agentic.bootstrap import DEFAULT_PLUGINS as PLUGINS
    monkeypatch.setenv("DB_TYPE", "file")
    bootstrap = Bootstrap(list(PLUGINS))
    # init_all must succeed without exceptions in file mode.
    await bootstrap.init_all()


async def test_bootstrap_runs_default_plugins_in_sqlite_mode(monkeypatch, tmp_path):
    from ark_agentic.bootstrap import DEFAULT_PLUGINS as PLUGINS
    reset_engine_cache()
    try:
        monkeypatch.setenv("DB_TYPE", "sqlite")
        monkeypatch.setenv(
            "DB_CONNECTION_STR",
            f"sqlite+aiosqlite:///{tmp_path}/boot.db",
        )
        bootstrap = Bootstrap(list(PLUGINS))
        await bootstrap.init_all()
    finally:
        reset_engine_cache()
        monkeypatch.delenv("DB_TYPE", raising=False)
        monkeypatch.delenv("DB_CONNECTION_STR", raising=False)


# ── Phase ordering / start-stop symmetry ─────────────────────────────


class _Recorder(BaseLifecycle):
    def __init__(self, name: str, log: list[str], *, fail_stop: bool = False):
        self.name = name
        self._log = log
        self._fail_stop = fail_stop

    async def init(self) -> None:
        self._log.append(f"{self.name}.init")

    async def start(self, ctx: Any) -> Any:
        self._log.append(f"{self.name}.start")
        return f"{self.name}-value"

    async def stop(self) -> None:
        if self._fail_stop:
            raise RuntimeError("stop failure")
        self._log.append(f"{self.name}.stop")


async def test_start_attaches_return_value_to_ctx_by_name():
    log: list[str] = []
    bootstrap = Bootstrap([_Recorder("alpha", log), _Recorder("beta", log)])

    class Ctx:
        pass

    ctx = Ctx()
    await bootstrap.init_all()
    await bootstrap.start_all(ctx)

    assert ctx.alpha == "alpha-value"
    assert ctx.beta == "beta-value"


async def test_stop_runs_in_reverse_start_order():
    log: list[str] = []
    bootstrap = Bootstrap([_Recorder("a", log), _Recorder("b", log), _Recorder("c", log)])

    class Ctx:
        pass

    await bootstrap.init_all()
    await bootstrap.start_all(Ctx())
    await bootstrap.stop_all()

    assert log == [
        "a.init", "b.init", "c.init",
        "a.start", "b.start", "c.start",
        "c.stop", "b.stop", "a.stop",
    ]


async def test_stop_failure_does_not_block_others():
    log: list[str] = []
    bootstrap = Bootstrap([
        _Recorder("a", log),
        _Recorder("b", log, fail_stop=True),
        _Recorder("c", log),
    ])

    class Ctx:
        pass

    await bootstrap.init_all()
    await bootstrap.start_all(Ctx())
    await bootstrap.stop_all()

    # b.stop raised; a.stop and c.stop must still run.
    assert "a.stop" in log
    assert "c.stop" in log


async def test_disabled_components_are_skipped():
    log: list[str] = []

    class Disabled(BaseLifecycle):
        name = "disabled"

        def is_enabled(self) -> bool:
            return False

        async def init(self) -> None:
            log.append("disabled.init")

    bootstrap = Bootstrap([Disabled(), _Recorder("kept", log)])
    await bootstrap.init_all()

    assert log == ["kept.init"]


async def test_lifespan_yields_after_start_and_stops_on_exit():
    log: list[str] = []
    bootstrap = Bootstrap([_Recorder("only", log)])

    class _App:
        class state: pass
        state = state()

    class Ctx:
        pass

    app = _App()
    ctx = Ctx()
    async with bootstrap.lifespan(app, ctx):
        # By yield-time start has run, ctx is published, stop has not run.
        assert log == ["only.init", "only.start"]
        assert app.state.ctx is ctx
        assert ctx.only == "only-value"

    # On exit stop ran.
    assert log[-1] == "only.stop"
