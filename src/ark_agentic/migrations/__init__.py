"""One-off migration logic, importable as a library.

CLI entrypoints for these migrations live under the repository's
top-level ``scripts/`` directory; this package exposes the underlying
``migrate(...)`` / ``migrate_dotfiles(...)`` functions used by the
runners and by the integration tests.
"""
