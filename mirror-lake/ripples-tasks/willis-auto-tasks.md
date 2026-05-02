# Auto Tasks

> Read by the Claude Code routine when triggered without an `api-text` payload.
> If `api-text` is provided at trigger time, it overrides this file.

## How to manage this file

- Add tasks before triggering the routine.
- Each H2 heading below `## Tasks` is one task.
- After a successful run, **clear the entries under `## Tasks`** — git history
  is the archive. The routine creates one PR per run; the PR body lists what
  was done. You can find any past run via `git log` on this file or the
  branches matching `claude/auto-tasks-*`.

## Task format

```
## [bug|feature|refactor|chore] short title

**Goal**: one sentence on what success means.
**Context**: optional — links, file paths, error messages, repro steps.
**Out of scope**: anything explicitly NOT to touch.
```

Tags drive the commit prefix:
- `bug`      → commit `fix: ...`
- `feature`  → commit `feat: ...`
- `refactor` → commit `refactor: ...`
- `chore`    → commit `chore: ...`

## Tasks

<!--
  No active tasks. Add tasks here, commit + push, then click "Run now" in the
  routine UI. After the PR is merged (or closed), clear this section back to
  this comment block.

  Or use the API trigger to bypass this file entirely:
    curl -X POST https://api.anthropic.com/v1/claude_code/routines/<id>/fire \
      -H "Authorization: Bearer <token>" \
      -H "anthropic-beta: experimental-cc-routine-2026-04-01" \
      -H "anthropic-version: 2023-06-01" \
      -H "Content-Type: application/json" \
      -d '{"text": "## [bug] short title\n\n**Goal**: ...\n**Context**: ..."}'
-->
