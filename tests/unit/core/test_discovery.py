"""Tests for ``BaseAgent`` filesystem discovery.

Covers the contract documented in
``core.runtime.discovery.discover_agents``:
  * concrete subclass with declared ``agent_id`` is registered
  * abstract intermediate base (no ``agent_id`` in ``__dict__``) is skipped
  * a re-export of one agent's class via a sibling ``__init__.py`` does
    not cause double registration
  * agent_id collision is silently skipped (idempotent re-scan)
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from ark_agentic.core.runtime.discovery import discover_agents
from ark_agentic.core.runtime.registry import AgentRegistry


def _scaffold_agents_pkg(root: Path, *, name: str = "agents_pkg") -> Path:
    """Create a minimal Python package usable as ``agents_root``.

    Returns the path of the package's ``agents/`` sub-directory — that's
    the value ``discover_agents`` expects.
    """
    pkg = root / name
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    agents = pkg / "agents"
    agents.mkdir()
    (agents / "__init__.py").write_text("", encoding="utf-8")
    return agents


def _write_agent(agents_root: Path, name: str, body: str) -> None:
    pkg = agents_root / name
    pkg.mkdir()
    (pkg / "__init__.py").write_text(body, encoding="utf-8")


def _stub_base_agent_subclass_source(
    *, class_name: str, agent_id: str | None,
) -> str:
    """A subclass whose constructor does NO real wiring (so tests don't
    require an LLM env). Sets the bare minimum instance attributes the
    registry contract uses."""
    aid_line = f'    agent_id = "{agent_id}"' if agent_id else ""
    return dedent(
        f"""
        from ark_agentic.core.runtime.base_agent import BaseAgent


        class {class_name}(BaseAgent):
        {aid_line}
            def __init_subclass__(cls, **kw):
                super().__init_subclass__(**kw)

            def __new__(cls, *args, **kwargs):
                # Bypass BaseAgent.__init__ wiring entirely for the test —
                # we only care about discovery's class-level inspection.
                inst = object.__new__(cls)
                inst.agent_id = getattr(cls, "agent_id", None) or "_test"
                return inst

            def __init__(self):  # noqa: D401 — mirrors __new__ override
                pass
        """
    ).strip() + "\n"


@pytest.fixture
def agents_root(tmp_path: Path, request: pytest.FixtureRequest) -> Path:
    # Unique package name per test — pkgutil caches modules by dotted
    # path, so reusing the same name across tests would let one test's
    # discovered classes leak into another via sys.modules.
    safe = request.node.name.replace("[", "_").replace("]", "_")
    return _scaffold_agents_pkg(tmp_path, name=f"pkg_{safe}")


def test_concrete_subclass_with_agent_id_is_registered(agents_root: Path):
    src = _stub_base_agent_subclass_source(
        class_name="FooAgent", agent_id="foo",
    )
    _write_agent(agents_root, "foo", src)

    registry = AgentRegistry()
    discover_agents(registry, agents_root)

    assert registry.list_ids() == ["foo"]


def test_intermediate_abstract_subclass_is_skipped(agents_root: Path):
    # No agent_id declared → intermediate / abstract; must not register.
    src = _stub_base_agent_subclass_source(
        class_name="AbstractMid", agent_id=None,
    )
    _write_agent(agents_root, "abstract_mid", src)

    registry = AgentRegistry()
    discover_agents(registry, agents_root)

    assert registry.list_ids() == []


def test_reexport_does_not_cause_double_registration(
    agents_root: Path, tmp_path: Path,
):
    # foo/agent.py defines the class; foo/__init__.py re-exports it.
    pkg = agents_root / "foo"
    pkg.mkdir()
    (pkg / "agent.py").write_text(
        _stub_base_agent_subclass_source(
            class_name="FooAgent", agent_id="foo",
        ),
        encoding="utf-8",
    )
    (pkg / "__init__.py").write_text(
        "from .agent import FooAgent\n__all__ = ['FooAgent']\n",
        encoding="utf-8",
    )

    registry = AgentRegistry()
    discover_agents(registry, agents_root)

    # FooAgent appears in both modules' vars() but __module__ filter +
    # seen-set dedup must keep it to a single registration.
    assert registry.list_ids() == ["foo"]


def test_id_collision_skips_silently(agents_root: Path):
    """Re-running discovery against the same root is a no-op (no duplicate)."""
    src = _stub_base_agent_subclass_source(
        class_name="FooAgent", agent_id="foo",
    )
    _write_agent(agents_root, "foo", src)

    registry = AgentRegistry()
    discover_agents(registry, agents_root)
    discover_agents(registry, agents_root)  # second run should be idempotent

    assert registry.list_ids() == ["foo"]


def test_missing_agents_root_is_no_op(tmp_path: Path):
    registry = AgentRegistry()
    discover_agents(registry, tmp_path / "does_not_exist")
    assert registry.list_ids() == []
