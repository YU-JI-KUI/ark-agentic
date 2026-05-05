# ark-agentic

Lightweight ReAct agent framework. Python backend + embedded React/Vite studio UI.

## Stack

- **Backend**: Python ≥3.10, packaging via `hatchling`, deps managed with `uv`
- **Server (optional)**: FastAPI + uvicorn + SQLAlchemy + APScheduler
- **Frontend (Studio)**: React 19 + Vite 7 + TypeScript 5.9, at `src/ark_agentic/plugins/studio/frontend/`
- **Tests**: pytest + pytest-asyncio (`asyncio_mode = auto`), 180s timeout, marker `slow` for integration
- **Lint/Type**: flake8, mypy, pyright (`extraPaths = ["src"]`)

## Project layout

```
src/ark_agentic/
  core/                  engine: runner, memory, sessions, storage, llm,
                         lifecycle, plugin protocol, bootstrap
  agents/                agent implementations (auto-discovered)
  plugins/               user-selectable features
    api/                 chat HTTP + middleware + default index.html
    jobs/                proactive job scheduler
    notifications/       notification dispatch
    studio/              admin console (incl. React frontend/)
  portal/                framework-internal landing site (NOT in wheel)
  app.py                 framework composition root (NOT in wheel)
  bootstrap.py           DEFAULT_PLUGINS for wheel consumers
  cli/main.py            `ark-agentic` console script
  migrations/            data migration helpers
tests/                   mirrors source tree
scripts/                 thin CLI runners → migrations/
```

## Architecture boundaries

Imports flow **downward only**:

```
app.py / portal/        ← framework-internal composition (not in wheel)
agents/ · plugins/      ← user-selectable features (Plugin)
core/                   ← engine (Lifecycle / Plugin protocols live here)
```

Hard rules:

- **`core/` is self-contained.** It must never import from `plugins/`,
  `agents/`, `portal/`, or `app.py`. If core needs something a feature
  provides, define a `Protocol` in core and let the feature implement it.
- **Features depend on core, not on each other.** Cross-feature wiring
  belongs in the composition root (`app.py`) via the shared `AppContext`.
- **`portal/` and `app.py` are framework-only** and excluded from the
  published wheel. Wheel consumers compose their own app from `core` +
  `plugins` + `bootstrap.DEFAULT_PLUGINS`.

### Lifecycle vs Plugin

Both live in `core/`. Structurally identical Protocols; the distinction is
**semantic**.

- **`Lifecycle`** (`core/lifecycle.py`) — base contract every long-lived
  component implements: `name`, `is_enabled()`, `init()`,
  `install_routes(app)`, `start(ctx)`, `stop()`. Used directly by **core
  runtime capabilities** that aren't optional features (`AgentsRuntime`,
  `TracingRuntime`, `Portal`).
- **`Plugin(Lifecycle)`** (`core/plugin.py`) — marker subtype for
  **user-selectable features** (`APIPlugin`, `JobsPlugin`,
  `NotificationsPlugin`, `StudioPlugin`). Picking a different feature set
  means swapping plugins; you do not swap `Lifecycle` components.

`Bootstrap` (`core/bootstrap.py`) drives any list of `Lifecycle` — it does
not care whether a component is a Plugin or a core runtime.

## Commands

### Python (from repo root)

- Install dev deps: `uv sync`
- All tests: `uv run pytest`
- Fast tests only: `uv run pytest -m "not slow"`
- Coverage: `uv run pytest --cov`
- Lint: `uv run flake8 src tests`
- Type check: `uv run mypy src` and/or `uv run pyright`
- Build: `uv build`

### Frontend (from `src/ark_agentic/plugins/studio/frontend/`)

- Install: `npm install`
- Dev: `npm run dev` (proxies `/api` and `/chat` to `localhost:8080`)
- Build: `npm run build` — must succeed; `dist/` ships in the wheel
- Lint: `npm run lint`

## Conventions

- Python target 3.10+. Modern type hints (`list[str]`, `X | None`).
- Async-first; pytest is `asyncio_mode = auto` — no `@pytest.mark.asyncio`
  needed for plain async tests.
- I/O uses `async/await` with `httpx`. Never `requests`.
- Complex data uses `pydantic.BaseModel`. Avoid bare `dict`.
- Package manager is `uv` only. Never `pip` or `poetry`.
- Don't add files under `data/` — gitignored.
- If you touch frontend, run `npm run build` so `dist/` stays consistent.

---

## Workflow by task type

Match the ceremony to the change. Don't over-design small fixes; don't
under-design structural work.

### Simple (`bug` / `chore` / docs / config)

Just fix it. No design pass.

- For a bug, write a regression test that **fails before** the fix and
  **passes after**. For chores/docs, skip new tests.
- Keep the diff in scope (see "Scope of change" below).

### Structural (`feature` / `refactor`)

Design top-down through the C4 layers **before writing code**. Each layer
has its own concern, interface, and abstraction:

1. **C1 — System context.** Does this change cross system boundaries
   (new external dependency, new protocol, new wheel consumer story)?
   Usually no — note it and move on.
2. **C2 — Containers.** Which containers does it touch (core engine,
   a specific plugin, frontend, CLI)? State the layering rule it must
   respect (see "Architecture boundaries"). Reject any design that pulls
   `core/` toward a feature.
3. **C3 — Components.** Define module boundaries and the **public
   `Protocol`** at each boundary. Identify the composition root that
   wires implementations to consumers. Apply SOLID here:
   - **SRP**: one reason to change per module.
   - **OCP**: extend via Plugin/Strategy, don't edit core for new features.
   - **LSP**: alternate implementations of a Protocol must be substitutable.
   - **ISP**: Protocols ≤ ~5 methods; no god-interfaces.
   - **DIP**: depend on Protocols, inject via `__init__`; no hardcoded
     `ClassName()` for swappable deps.
4. **C4 — Code.** Now implement. By this point the boundaries are settled
   and the diff should be mechanical.

For non-trivial refactors, write the design (even briefly) before touching
code, and confirm with the user when it changes a public Protocol or
crosses a layer boundary.

### Test responsibility by task

| Task tag       | Tests                                                                |
|----------------|----------------------------------------------------------------------|
| `feature`      | Required: happy path + ≥1 boundary case. Errors if behavior is non-trivial. |
| `bug`          | Required: regression test (fails before, passes after).              |
| `refactor`     | Existing tests must pass before and after. Add new tests only if asked. |
| `chore`/docs   | Skip new tests. Run existing tests if code paths could be affected.  |

If you can't write a clean test for new code, that's a **design smell** —
fix the design, not the test.

---

## Design principles (summary)

- **The right amount of design** — not no design, not over-design. Solve
  current concrete problems, not imagined futures (KISS, YAGNI).
- **Rule of Three** — extract on the third repetition, not the first.
  Wrong abstraction is worse than duplication.
- **Composition > inheritance** — inheritance depth ≤ 2.
- **Law of Demeter** — no `a.b.c.method()` chains.
- **Fail fast** — validate at function entry, not deep in the call stack.
- **Type safety** — full type hints; no bare `dict`, no `Any` without
  justification.
- **Search before adding** — grep for existing similar logic. Reuse,
  refactor, or extend. Never copy-paste.

### Self-check before committing

1. Single responsibility per module/class?
2. Every abstraction solves a real, current problem?
3. Function ≤ 40 lines, nesting ≤ 3 levels?
4. Boundary cases covered (none / empty / zero / error) — code AND tests?
5. Errors fail fast at entry, not buried?
6. Types complete?
7. Tests match the task tag?
8. Diff is in scope (next section)?

## Scope of change

**Every changed line should trace back to the task.** Smaller diff > tidier
diff.

- **Required**: remove imports, helpers, and branches **your** changes
  orphaned.
- **Allowed**: dead-code cleanup limited to files you're already editing,
  provably unreferenced (zero grep hits), not a public API — list each
  deletion in the PR description.
- **Not allowed**: drive-by renames/reformatting, refactors of working
  code outside the task, style/lint fixes in untouched files, deleting
  dead code in modules you're not otherwise touching.

When in doubt, ask. Match existing style.

---

## Testing

- **AAA pattern** — Arrange / Act / Assert, separated by blank lines.
- **One behavior per test** — name `test_<function>_<scenario>`.
- **Independent & order-free** — no shared mutable state.
- **Mock the boundary** (LLM, DB, network), not the unit under test. Use
  `unittest.mock.AsyncMock` for async deps.
- **Specific assertions** — `assert result.status == "success"`, not
  `assert result`.
- **Fixtures** when setup repeats 3+ times (Rule of Three).

### Test pyramid

1. **Unit** (most): single function/method with mocked deps.
2. **Integration** (some): module collaboration, real deps where cheap.
3. **E2E** (few): full flow via FastAPI `TestClient` / `httpx.AsyncClient`.

## "Done" criteria

1. `uv run pytest -m "not slow"` passes.
2. Tests for new code exist (per the table above).
3. If types changed: `uv run mypy src` introduces no new errors.
4. If frontend changed: `npm run build` succeeds.
5. Diff is in scope.

## Unattended runs (routine)

- Attempt **one** focused fix on a failing new test. Still failing → mark
  the task ⚠️ partial, leave the test in place (skipped/xfailed with
  reason), continue.
- State assumptions in the PR description rather than guessing silently.
- Never push to `main` / `master` / `develop`. Only `claude/*` branches.
- Never modify CI configs, `pyproject.toml [build-system]`, `.env*`, or
  anything under `data/` without an explicit task instruction.
