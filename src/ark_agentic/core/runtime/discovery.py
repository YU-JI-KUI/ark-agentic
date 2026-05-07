"""Filesystem-rooted ``BaseAgent`` discovery.

Scans an ``agents_root`` directory, recursively imports every
sub-package, finds every ``BaseAgent`` subclass that declared its own
``agent_id`` (i.e. ``"agent_id" in cls.__dict__``), and registers
``cls()`` against the supplied ``AgentRegistry``.

Intermediate abstract classes that inherit ``BaseAgent`` without
declaring ``agent_id`` are silently skipped — they exist for code
sharing, not for registration. Re-exports are filtered out by
``__module__`` prefix so importing an agent class in a sibling
``__init__.py`` doesn't double-register it.
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Iterator

from .base_agent import BaseAgent

if TYPE_CHECKING:
    from .registry import AgentRegistry
    from types import ModuleType

logger = logging.getLogger(__name__)


def _agents_dir_to_pkg_path(agents_root: Path) -> str:
    """Walk up from ``agents_root`` collecting parent dirs while each has
    an ``__init__.py``. Reverse the names to form a dotted package path.

    Adds the topmost non-package parent to ``sys.path`` so the resulting
    dotted import resolves under any layout (``src/pkg/agents`` works
    when ``src/`` is the parent that gets added).
    """
    agents_root = agents_root.resolve()
    parts: list[str] = [agents_root.name]
    cursor = agents_root.parent
    while (cursor / "__init__.py").exists():
        parts.append(cursor.name)
        cursor = cursor.parent
    parts.reverse()
    parent = str(cursor)
    if parent not in sys.path:
        sys.path.insert(0, parent)
    return ".".join(parts)


def _iter_base_agent_subclasses(pkg: "ModuleType") -> Iterator[type[BaseAgent]]:
    """Yield every ``BaseAgent`` subclass *defined* under ``pkg`` (not
    re-exported), in deterministic discovery order.

    Filters by ``__module__.startswith(pkg.__name__)`` to skip
    re-exports — e.g. ``from .agent import InsuranceAgent`` inside a
    sibling ``__init__.py`` would otherwise yield the same class twice.
    """
    seen: set[type[BaseAgent]] = set()
    for _finder, name, _ispkg in pkgutil.walk_packages(
        pkg.__path__, prefix=f"{pkg.__name__}.",
    ):
        try:
            mod = importlib.import_module(name)
        except Exception:
            logger.warning(
                "Module %r failed to import during agent discovery; skipped",
                name, exc_info=True,
            )
            continue
        for obj in vars(mod).values():
            if not isinstance(obj, type):
                continue
            if not issubclass(obj, BaseAgent) or obj is BaseAgent:
                continue
            if obj in seen:
                continue
            if not obj.__module__.startswith(pkg.__name__):
                continue
            seen.add(obj)
            yield obj


def discover_agents(
    registry: "AgentRegistry",
    agents_root: Path,
) -> None:
    """Discover and register every ``BaseAgent`` subclass under ``agents_root``.

    - A subclass is registered iff it declares ``agent_id`` in its own
      ``__dict__`` (intermediate abstract bases without ``agent_id``
      are skipped — they exist for code sharing).
    - If a class's ``agent_id`` is already in the registry, it is
      skipped silently (idempotency: framework agents may be scanned
      first, then re-scanned by user roots).
    - Per-agent construction failures are logged and skipped.
    """
    if not agents_root.is_dir():
        logger.warning(
            "Agents root %s is not a directory; no agents discovered",
            agents_root,
        )
        return

    pkg_path = _agents_dir_to_pkg_path(agents_root)
    try:
        pkg = importlib.import_module(pkg_path)
    except Exception:
        logger.warning(
            "Agents package %r failed to import; no agents discovered",
            pkg_path, exc_info=True,
        )
        return

    discovered = 0
    for cls in _iter_base_agent_subclasses(pkg):
        if "agent_id" not in cls.__dict__:
            continue
        agent_id = cls.agent_id
        if agent_id in registry.list_ids():
            logger.debug(
                "Agent %r already registered; skipping discovery of %s",
                agent_id, cls.__name__,
            )
            continue
        try:
            instance = cls()
        except Exception:
            logger.warning(
                "Agent %s (id=%r) failed to construct; skipped",
                cls.__name__, agent_id, exc_info=True,
            )
            continue
        registry.register(agent_id, instance)
        logger.info("Registered agent: %s (id=%s)", cls.__name__, agent_id)
        discovered += 1

    if discovered == 0:
        logger.info("No agents discovered under %s", agents_root)
