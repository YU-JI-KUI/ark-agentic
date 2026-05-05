"""One-off data migration scripts (not packaged in the wheel).

Run via ``uv run python scripts/migrations/<name>.py ...``. The
underlying ``migrate(...)`` / ``migrate_dotfiles(...)`` functions are
imported by the integration tests under ``tests/integration/``.
"""
