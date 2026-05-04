#!/usr/bin/env python
"""CLI runner — see ``ark_agentic.migrations.file_to_sqlite`` for the
underlying logic and arguments."""

from __future__ import annotations

from ark_agentic.migrations.file_to_sqlite import main

if __name__ == "__main__":
    raise SystemExit(main())
