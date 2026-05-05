"""Bootstrap orchestrator tests.

Validates the lifecycle phases (``init`` / ``start`` / ``stop``) and
their ordering / idempotency. Uses ``with_defaults=False`` for tests
exercising arbitrary recorder components; the always-on lifecycle
defaults (AgentsLifecycle + TracingLifecycle) are covered by separate
integration tests.
"""

from __future__ import annotations

from typing import Any

from ark_agentic.core.db.engine import reset_engine_cache
from ark_agentic.core.protocol.bootstrap import Bootstrap
from ark_agentic.core.protocol.lifecycle import BaseLifecycle


async def test_bootstrap_runs_with_defaults_in_file_mode(monkeypatch):
    monkeypatch.setenv("DB_TYPE", "file")
    bootstrap = Bootstrap()
    # init() must succeed without exceptions in file mode.
    await bootstrap.init()


async def test_bootstrap_runs_with_defaults_in_sqlite_mode(
    monkeypatch, tmp_path,
):
    reset_engine_cache()
    try:
        monkeypatch.setenv("DB_TYPE", "sqlite")
        monkeypatch.setenv(
            "DB_CONNECTION_STR",
            f"sqlite+aiosqlite:///{tmp_path}/boot.db",
        )
        bootstrap = Bootstrap()
        await bootstrap.init()
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
    bootstrap = Bootstrap(
        [_Recorder("alpha", log), _Recorder("beta", log)],
        with_defaults=False,
    )

    class Ctx:
        pass

    ctx = Ctx()
    await bootstrap.start(ctx)

    assert ctx.alpha == "alpha-value"
    assert ctx.beta == "beta-value"


async def test_start_runs_init_first_then_start_in_order():
    log: list[str] = []
    bootstrap = Bootstrap(
        [_Recorder("a", log), _Recorder("b", log), _Recorder("c", log)],
        with_defaults=False,
    )

    class Ctx:
        pass

    await bootstrap.start(Ctx())

    assert log == [
        "a.init", "b.init", "c.init",
        "a.start", "b.start", "c.start",
    ]


async def test_stop_runs_in_reverse_start_order():
    log: list[str] = []
    bootstrap = Bootstrap(
        [_Recorder("a", log), _Recorder("b", log), _Recorder("c", log)],
        with_defaults=False,
    )

    class Ctx:
        pass

    await bootstrap.start(Ctx())
    await bootstrap.stop()

    assert log[-3:] == ["c.stop", "b.stop", "a.stop"]


async def test_init_is_idempotent():
    log: list[str] = []
    bootstrap = Bootstrap([_Recorder("only", log)], with_defaults=False)

    await bootstrap.init()
    await bootstrap.init()  # second call is no-op

    assert log == ["only.init"]


async def test_start_does_not_double_init_when_init_was_called_first():
    log: list[str] = []
    bootstrap = Bootstrap([_Recorder("only", log)], with_defaults=False)

    class Ctx:
        pass

    await bootstrap.init()
    await bootstrap.start(Ctx())

    # init runs once even though start would otherwise also call it.
    assert log.count("only.init") == 1
    assert "only.start" in log


async def test_stop_failure_does_not_block_others():
    log: list[str] = []
    bootstrap = Bootstrap(
        [
            _Recorder("a", log),
            _Recorder("b", log, fail_stop=True),
            _Recorder("c", log),
        ],
        with_defaults=False,
    )

    class Ctx:
        pass

    await bootstrap.start(Ctx())
    await bootstrap.stop()

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

    bootstrap = Bootstrap(
        [Disabled(), _Recorder("kept", log)], with_defaults=False,
    )
    await bootstrap.init()

    assert log == ["kept.init"]


# ── default-components contract ──────────────────────────────────────


async def test_default_components_include_agents_and_tracing():
    """Bootstrap with defaults always loads AgentsLifecycle first and
    TracingLifecycle last — they're framework-mandatory."""
    bootstrap = Bootstrap()
    names = [c.name for c in bootstrap.components]

    assert names[0] == "registry"
    assert names[-1] == "tracing"


async def test_user_plugins_sit_between_defaults():
    plugin = _Recorder("custom", [])
    bootstrap = Bootstrap([plugin])
    names = [c.name for c in bootstrap.components]

    assert names[0] == "registry"
    assert "custom" in names
    assert names[-1] == "tracing"
