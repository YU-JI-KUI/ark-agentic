"""One-shot migration: relocate ``.last_job_<job_id>`` dotfiles.

Before this commit the scanner kept per-(user, job) idempotency markers
under ``data/ark_memory/{agent_id}/{user_id}/.last_job_<job_id>`` because
the agent_state KV repository was rooted at the memory workspace. Jobs
now own their own storage layer and look at
``{JOB_RUNS_DIR}/{user_id}/.{job_id}`` instead, so this script moves any
existing dotfiles into the new layout.

``.last_dream`` markers stay in place — ``FileMemoryRepository`` already
reads them at the same path.

Idempotent: source files that no longer exist (or whose target already
exists) are skipped silently.

The CLI runner lives at ``scripts/migrate_agent_state_dotfiles.py``::

    uv run python scripts/migrate_agent_state_dotfiles.py \\
        --memory-root data/ark_memory \\
        --job-runs-dir data/ark_job_runs
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_LAST_JOB_PREFIX = ".last_job_"


def migrate_dotfiles(
    memory_root: Path,
    job_runs_dir: Path,
    *,
    dry_run: bool = False,
) -> tuple[int, int]:
    """Walk ``memory_root/{agent_id}/{user_id}/.last_job_<job_id>`` and move
    each dotfile to ``job_runs_dir/{user_id}/.<job_id>``.

    ``memory_root`` is the data root (e.g. ``data/ark_memory``). Each
    direct child is treated as an agent workspace. Identical ``job_id``
    markers across multiple agents collapse to one row at the destination
    — by construction, each proactive job has a globally unique
    ``job_id`` so no real collision can happen.

    Returns ``(moved, skipped)``.
    """
    moved = 0
    skipped = 0

    if not memory_root.exists():
        logger.warning(
            "memory_root %s does not exist; nothing to migrate", memory_root,
        )
        return 0, 0

    for agent_dir in sorted(memory_root.iterdir()):
        if not agent_dir.is_dir():
            continue
        for user_dir in sorted(agent_dir.iterdir()):
            if not user_dir.is_dir():
                continue
            for entry in sorted(user_dir.iterdir()):
                if not entry.is_file():
                    continue
                if not entry.name.startswith(_LAST_JOB_PREFIX):
                    continue
                job_id = entry.name[len(_LAST_JOB_PREFIX):]
                target = job_runs_dir / user_dir.name / f".{job_id}"
                if target.exists():
                    logger.debug(
                        "skip %s — target %s already exists",
                        entry, target,
                    )
                    skipped += 1
                    continue
                if dry_run:
                    logger.info("[dry-run] would move %s → %s", entry, target)
                    moved += 1
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                entry.rename(target)
                logger.info("moved %s → %s", entry, target)
                moved += 1

    return moved, skipped


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--memory-root", type=Path, default=Path("data/ark_memory"),
        help="Source root containing per-agent workspaces (default: data/ark_memory)",
    )
    parser.add_argument(
        "--job-runs-dir", type=Path, default=Path("data/ark_job_runs"),
        help="Destination root: data/ark_job_runs",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    moved, skipped = migrate_dotfiles(
        args.memory_root, args.job_runs_dir, dry_run=args.dry_run,
    )
    logger.info("Done: moved=%d skipped=%d", moved, skipped)


if __name__ == "__main__":
    main()
