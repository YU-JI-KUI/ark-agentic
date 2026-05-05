# ark-agentic

Lightweight ReAct agent framework. Python backend + embedded React/Vite studio UI.

## Stack

Python ≥3.12 (uv, hatchling) · FastAPI + SQLAlchemy + APScheduler · React 19 + Vite 7 + TS 5.9 at `src/ark_agentic/plugins/studio/frontend/` · pytest (`asyncio_mode = auto`, 180s timeout, `slow` marker) · flake8 / mypy / pyright (`extraPaths = ["src"]`).

## Behavioral guidelines

- **Think before coding.** State assumptions; if unclear, ask. If multiple interpretations exist, surface them — don't pick silently.
- **Simplicity first.** No abstractions, configurability, or error handling that wasn't asked for. Wrong abstraction is worse than duplication — extract on the third repetition, not the first.
- **Surgical changes.** Match existing style. Don't refactor working code outside the task. See "Scope of change" for the hard rule.
- **Goal-driven.** Bug → write the regression test that fails first. Feature → define the boundary case before coding. Refactor → existing tests must pass before and after.

## Project layout

```
src/ark_agentic/
  core/                  engine — must not import from plugins/agents/portal/app
    protocol/            Lifecycle/Plugin Protocols, Bootstrap, AppContext
    runtime/             agent execution (Runner, Registry, Callbacks, Guard …) + AgentsLifecycle
    observability/       OTel decorators, tracing setup, TracingLifecycle
    session/             SessionManager, JSONL format, compaction, history merge
    storage/ ...         storage backends, db, etc.
  agents/                auto-discovered agent implementations
  plugins/{api,jobs,notifications,studio}   user-selectable features
  portal/                framework-internal landing site (NOT in wheel)
  app.py                 framework composition root (NOT in wheel)
  cli/main.py            `ark-agentic` console script
tests/                   mirrors source tree
```

## Architecture boundaries

Imports flow **downward only**:

```
app.py / portal/        ← framework-internal composition (not in wheel)
agents/ · plugins/      ← user-selectable features (Plugin)
core/                   ← engine (Lifecycle / Plugin protocols live here)
```

Hard rules:

- **`core/` is self-contained.** Never imports from `plugins/`, `agents/`, `portal/`, or `app.py`. If core needs something a feature provides, define a `Protocol` in core and let the feature implement it.
- **Features depend on core, not on each other.** Cross-feature wiring belongs in `app.py` via the shared `AppContext`.
- **`portal/` and `app.py` are framework-only** and excluded from the published wheel. Wheel consumers build their own composition root with `Bootstrap(plugins=[...])` — the always-on `AgentsLifecycle` + `TracingLifecycle` are auto-loaded by `Bootstrap` itself and cannot be deselected.

### Lifecycle vs Plugin

Both live in `core/protocol/`. Structurally identical Protocols; the distinction is **semantic**.

- **`Lifecycle`** (`core/protocol/lifecycle.py`) — base contract for long-lived components: `name`, `is_enabled()`, `init()`, `install_routes(app)`, `start(ctx)`, `stop()`. Used by core runtime capabilities that aren't optional features (`AgentsLifecycle`, `TracingLifecycle`, `Portal`).
- **`Plugin(Lifecycle)`** (`core/protocol/plugin.py`) — marker subtype for user-selectable features (`APIPlugin`, `JobsPlugin`, `NotificationsPlugin`, `StudioPlugin`).

`Bootstrap` (`core/protocol/bootstrap.py`) drives any list of `Lifecycle` — it does not care whether a component is a Plugin or a core runtime. Tests pass `with_defaults=False` to bypass the auto-loaded core runtimes.

## Project conventions

- Package manager is `uv` only. Never `pip` or `poetry`.
- I/O uses `httpx`. Never `requests`.
- Inheritance depth ≤ 2; prefer composition.
- Functions ≤ 80 lines, nesting ≤ 3 levels.
- Don't add files under `data/` — gitignored.
- If you touch the frontend, run `npm run build` so `dist/` stays consistent (it ships in the wheel).

## Commands

| Task              | Command |
|-------------------|---------|
| Tests (fast)      | `uv run pytest -m "not slow"` |
| Tests (all + cov) | `uv run pytest --cov` |
| Lint / type       | `uv run flake8 src tests` · `uv run mypy src` · `uv run pyright` |
| Build             | `uv build` |
| Frontend dev      | `cd src/ark_agentic/plugins/studio/frontend && npm run dev` |
| Frontend build    | `cd src/ark_agentic/plugins/studio/frontend && npm run build` |

Frontend dev server proxies `/api` and `/chat` to `localhost:8080`.

## Workflow by task type

Match ceremony to scope.

**Simple (`bug` / `chore` / docs / config)** — just fix it. Bug requires a regression test that fails before and passes after. Otherwise no new tests.

**Structural (`feature` / `refactor`)** — design top-down through the C4 layers **before writing code**. Do not skip layers.

1. **C1 — System context.** Does this cross system boundaries (new external dep, new protocol, new wheel-consumer story)? Usually no — note and move on.
2. **C2 — Containers.** Which containers does it touch (`core`, a specific plugin, frontend, CLI)? State the layering rule it must respect (see "Architecture boundaries"). Reject any design that pulls `core/` toward a feature.
3. **C3 — Components.** Define module boundaries and the **public `Protocol`** at each boundary. Identify the composition root that wires implementations to consumers. Apply SOLID:
   - **SRP** — one reason to change per module.
   - **OCP** — extend via Plugin/Strategy; don't edit core for new features.
   - **LSP** — alternate implementations of a Protocol must be substitutable.
   - **ISP** — Protocols ≤ ~7 methods; no god-interfaces.
   - **DIP** — depend on Protocols, inject via `__init__`; no hardcoded `ClassName()` for swappable deps.
4. **C4 — Code.** Implement. By this point boundaries are settled and the diff should be mechanical.

Write the design briefly (even just a few lines) before touching code. **Confirm with the user when the change touches a public `Protocol` or crosses a layer boundary.**

If you can't write a clean test for new code, that's a design smell — fix the design, not the test.

### Test responsibility

| Task tag     | Tests                                                                       |
|--------------|-----------------------------------------------------------------------------|
| `feature`    | Required: happy path + ≥1 boundary case. Errors if behavior is non-trivial. |
| `bug`        | Required: regression test (fails before, passes after).                     |
| `refactor`   | Existing tests must pass before and after. Add new tests only if asked.     |
| `chore`/docs | Skip new tests. Run existing tests if affected paths could regress.         |

### Test conventions

- AAA — Arrange / Act / Assert, blank lines between.
- One behavior per test; name `test_<function>_<scenario>`.
- Mock the boundary (LLM, DB, network), not the unit. Use `unittest.mock.AsyncMock` for async deps.
- Specific assertions: `assert result.status == "success"`, not `assert result`.
- Fixtures only when setup repeats 3+ times.

## Scope of change

**Every changed line should trace back to the task.** Smaller diff > tidier diff.

- **Required:** remove imports, helpers, and branches **your** changes orphaned.
- **Allowed:** dead-code cleanup limited to files you're already editing, provably unreferenced (zero grep hits), not a public API — list each deletion in the PR description.
- **Not allowed:** drive-by renames/reformatting, refactors of working code outside the task, style/lint fixes in untouched files, deleting dead code in modules you're not otherwise touching.

When in doubt, ask.

## "Done" criteria

1. `uv run pytest -m "not slow"` passes.
2. Tests for new code match the task table.
3. If types changed: `uv run mypy src` introduces no new errors.
4. If frontend changed: `npm run build` succeeds.
5. Diff is in scope.

## Unattended runs

- One focused fix attempt on a failing new test. Still failing → mark task ⚠️ partial, leave the test in place (skipped/xfailed with reason), continue.
- State assumptions in the PR description rather than guessing silently.
- Never push to `main` / `master` / `develop`. Only `claude/*` branches.
- Never modify CI configs, `pyproject.toml [build-system]`, `.env*`, or anything under `data/` without an explicit task instruction.
