"""Filesystem-rooted agent discovery.

Generic replacement for the historical ``ark_agentic.agents.register_all``
shim. Core does not import any specific agents package — instead, it
takes a filesystem ``agents_root`` (resolved via
``core.utils.env.get_agents_root``) and dynamically loads every direct
sub-package that exposes a ``register(registry, **opts)`` function.

Wheel consumers whose agents live in ``src/<their_pkg>/agents`` are
discovered the same way the framework's own ``src/ark_agentic/agents``
is — no package-name string is hardcoded in core.
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .registry import AgentRegistry

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


def discover_and_register_agents(
    registry: "AgentRegistry",
    agents_root: Path,
    **opts: Any,
) -> None:
    """Discover and register every agent package under ``agents_root``.

    Each direct sub-directory that is a Python package (has
    ``__init__.py``) is imported by its full dotted path so relative
    imports inside the agent (``from .agent import …``) resolve. If the
    sub-package defines ``register(registry, **opts)`` it is called.
    Per-agent failures are logged and skipped.
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
    for _finder, name, ispkg in pkgutil.iter_modules(pkg.__path__):
        if not ispkg:
            continue
        try:
            mod = importlib.import_module(f"{pkg_path}.{name}")
        except Exception:
            logger.warning(
                "Agent package %r failed to import; skipped", name,
                exc_info=True,
            )
            continue

        register = getattr(mod, "register", None)
        if register is None:
            continue
        try:
            register(registry, **opts)
            logger.info("Registered agent: %s", name)
            discovered += 1
        except Exception:
            logger.warning(
                "Failed to register agent %r; skipped", name, exc_info=True,
            )

    if discovered == 0:
        logger.info("No agents discovered under %s", agents_root)
