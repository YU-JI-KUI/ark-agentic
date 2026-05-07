"""Bootstrap orchestrator tests.

Validates the lifecycle phases (``init`` / ``start`` / ``stop``) and
their ordering / idempotency. The orchestration tests use
``Bootstrap._from_components`` so arbitrary recorders aren't sandwiched
between the framework defaults; the always-on lifecycle defaults
(AgentsLifecycle + TracingLifecycle) are exercised through the public
constructor in dedicated tests below.
"""

from __future__ import annotations

from typing import Any

from ark_agentic.core.protocol.bootstrap import Bootstrap
from ark_agentic.core.protocol.lifecycle import BaseLifecycle
from ark_agentic.core.storage.database.engine import reset_engine_cache


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
    bootstrap = Bootstrap._from_components(
        [_Recorder("alpha", log), _Recorder("beta", log)],
    )

    class Ctx:
        pass

    ctx = Ctx()
    await bootstrap.start(ctx)

    assert ctx.alpha == "alpha-value"
    assert ctx.beta == "beta-value"


async def test_start_runs_init_first_then_start_in_order():
    log: list[str] = []
    bootstrap = Bootstrap._from_components(
        [_Recorder("a", log), _Recorder("b", log), _Recorder("c", log)],
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
    bootstrap = Bootstrap._from_components(
        [_Recorder("a", log), _Recorder("b", log), _Recorder("c", log)],
    )

    class Ctx:
        pass

    await bootstrap.start(Ctx())
    await bootstrap.stop()

    assert log[-3:] == ["c.stop", "b.stop", "a.stop"]


async def test_init_is_idempotent():
    log: list[str] = []
    bootstrap = Bootstrap._from_components([_Recorder("only", log)])

    await bootstrap.init()
    await bootstrap.init()  # second call is no-op

    assert log == ["only.init"]


async def test_start_does_not_double_init_when_init_was_called_first():
    log: list[str] = []
    bootstrap = Bootstrap._from_components([_Recorder("only", log)])

    class Ctx:
        pass

    await bootstrap.init()
    await bootstrap.start(Ctx())

    # init runs once even though start would otherwise also call it.
    assert log.count("only.init") == 1
    assert "only.start" in log


async def test_stop_failure_does_not_block_others():
    log: list[str] = []
    bootstrap = Bootstrap._from_components(
        [
            _Recorder("a", log),
            _Recorder("b", log, fail_stop=True),
            _Recorder("c", log),
        ],
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

    bootstrap = Bootstrap._from_components(
        [Disabled(), _Recorder("kept", log)],
    )
    await bootstrap.init()

    assert log == ["kept.init"]


async def test_name_collision_raises():
    """Two components publishing the same ctx slot is a configuration error."""
    log: list[str] = []
    bootstrap = Bootstrap._from_components(
        [_Recorder("dup", log), _Recorder("dup", log)],
    )

    class Ctx:
        pass

    import pytest
    with pytest.raises(RuntimeError, match="collision"):
        await bootstrap.start(Ctx())


# ── default-components contract ──────────────────────────────────────


async def test_default_components_include_storage_agents_and_tracing():
    """Bootstrap with defaults loads CoreStorageLifecycle first (so the
    central session/user-memory schema exists before any component touches
    the DB), AgentsLifecycle second, and TracingLifecycle last — all three
    are framework-mandatory and their ordering is not configurable."""
    bootstrap = Bootstrap()
    names = [c.name for c in bootstrap.components]

    assert names[0] == "core_storage"
    assert names[1] == "agent_registry"
    assert names[-1] == "tracing"


async def test_user_plugins_sit_between_defaults():
    plugin = _Recorder("custom", [])
    bootstrap = Bootstrap([plugin])
    names = [c.name for c in bootstrap.components]

    assert names[0] == "core_storage"
    assert names[1] == "agent_registry"
    assert "custom" in names
    assert names[-1] == "tracing"
    assert names.index("custom") > names.index("agent_registry")
    assert names.index("custom") < names.index("tracing")


async def test_agent_registry_property_seeds_framework_registry():
    """CLI scaffolds register custom agents through the public registry
    property before ``start()``."""
    bootstrap = Bootstrap()
    registry = bootstrap.agent_registry
    assert registry is not None
    # Same instance is exposed; downstream populates it.
    assert bootstrap.agent_registry is registry


async def test_test_mode_bootstrap_has_no_agent_registry():
    """``_from_components`` skips defaults — agent_registry must raise."""
    bootstrap = Bootstrap._from_components([])
    import pytest
    with pytest.raises(RuntimeError):
        _ = bootstrap.agent_registry
