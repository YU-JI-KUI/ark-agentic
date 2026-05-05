"""Static check: every ALTER op in every alembic ``versions/*.py`` file must
go through ``op.batch_alter_table`` (i.e. be a ``batch_op.*`` call, not a
direct ``op.*`` call).

SQLite doesn't support ``ALTER TABLE ... ALTER COLUMN`` / ``DROP COLUMN``
and friends; alembic emulates them via ``batch_alter_table`` (recreate +
copy + rename). Migrations that call ``op.alter_column`` directly will
break on SQLite even if they pass on PostgreSQL.

This test enforces the discipline at PR-review time so a slip can't ship.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import ark_agentic

# Ops that mutate existing tables and need batch_alter_table on SQLite.
# ``op.add_column`` is safe outside batch on SQLite (CREATE TABLE syntax
# supports it) and is intentionally NOT in this set.
_FORBIDDEN_TOP_LEVEL = frozenset({
    "alter_column",
    "drop_column",
    "drop_constraint",
    "create_foreign_key",
    "create_unique_constraint",
    "create_check_constraint",
})


def _discover_version_files() -> list[Path]:
    root = Path(ark_agentic.__file__).parent
    return sorted(
        f
        for d in root.rglob("migrations/versions")
        for f in d.glob("*.py")
        if f.name != "__init__.py"
    )


def _violations(version_file: Path) -> list[str]:
    tree = ast.parse(version_file.read_text(encoding="utf-8"))
    bad: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute):
            continue
        if not isinstance(func.value, ast.Name):
            continue
        if func.value.id != "op":
            continue
        if func.attr in _FORBIDDEN_TOP_LEVEL:
            bad.append(f"line {node.lineno}: op.{func.attr}")
    return bad


_VERSION_FILES = _discover_version_files()


def test_at_least_one_migration_discovered() -> None:
    """Sanity: the discovery itself must find files; otherwise the lint is
    silently a no-op and doesn't catch anything."""
    assert _VERSION_FILES, (
        "No migrations/versions/*.py files discovered — lint is a no-op."
    )


@pytest.mark.parametrize(
    "version_file",
    _VERSION_FILES,
    ids=[str(f.relative_to(Path(ark_agentic.__file__).parent))
         for f in _VERSION_FILES],
)
def test_alter_ops_use_batch_alter_table(version_file: Path) -> None:
    bad = _violations(version_file)
    assert not bad, (
        f"{version_file.name}: top-level ops bypass batch_alter_table: "
        f"{bad}. Wrap in "
        f"`with op.batch_alter_table('<table>') as batch_op:` and call "
        f"`batch_op.<op>(...)` for SQLite portability."
    )
