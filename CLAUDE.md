# ark-agentic

Lightweight ReAct agent framework. Python backend + embedded React/Vite studio UI.

## Stack

- **Backend**: Python ≥3.10, packaging via `hatchling`, deps managed with `uv`
- **Server (optional)**: FastAPI + uvicorn + SQLAlchemy + APScheduler
- **Frontend (Studio)**: React 19 + Vite 7 + TypeScript 5.9, at `src/ark_agentic/studio/frontend/`
- **Tests**: pytest + pytest-asyncio (`asyncio_mode = auto`), 180s timeout, marker `slow` for integration
- **Lint/Type**: flake8, mypy, pyright (`extraPaths = ["src"]`)

## Project layout

- `src/ark_agentic/` — main package
- `src/ark_agentic/cli/main.py` — entrypoint (`ark-agentic` console script)
- `src/ark_agentic/studio/frontend/` — React studio UI; built into `dist/`, served by FastAPI under `/studio/`
- `src/ark_agentic/agents/` — agent implementations
- `tests/` — pytest tests (mirror the source tree: `tests/test_<module>.py`)

## Architecture boundaries

The codebase is layered. Imports only flow **downward**:

```
app.py / portal/        ← framework-internal composition (not in wheel)
agents/ · plugins/      ← user-selectable features (Plugin)
core/                   ← engine: runner, memory, sessions, storage, llm, lifecycle
```

Rules:

- **`core/` is self-contained.** It must never import from `plugins/`, `agents/`,
  `portal/`, or `app.py`. If core needs something a feature provides, define a
  `Protocol` in core and let the feature implement it.
- **Features (`plugins/*`, `agents/*`) depend on core**, not on each other.
  Cross-feature wiring belongs in the composition root (`app.py`) via the
  shared `AppContext`.
- **`portal/` and `app.py` are framework-only** and excluded from the published
  wheel. Wheel consumers compose their own app from `core` + `plugins` +
  `bootstrap.DEFAULT_PLUGINS`.

### Lifecycle vs Plugin

Both live in `core/`. They are structurally identical Protocols; the distinction
is **semantic**.

- **`Lifecycle`** (`core/lifecycle.py`) — the base contract every long-lived
  component implements: `name`, `is_enabled()`, `init()`, `install_routes(app)`,
  `start(ctx)`, `stop()`. Used directly by **core runtime capabilities** that
  are not optional features (e.g. `AgentsRuntime`, `TracingRuntime`, `Portal`).
- **`Plugin(Lifecycle)`** (`core/plugin.py`) — marker subtype for
  **user-selectable features** (`APIPlugin`, `JobsPlugin`, `NotificationsPlugin`,
  `StudioPlugin`). Picking a different feature set means swapping plugins; you
  do not swap `Lifecycle` components.

Bootstrap (`core/bootstrap.py`) drives any list of `Lifecycle` — it does not
care whether a component is a Plugin or a core runtime.

## Commands

### Python (from repo root)

- Install dev deps: `uv sync`
- All tests: `uv run pytest`
- Fast tests only: `uv run pytest -m "not slow"`
- Verbose with short traceback: `uv run pytest -v --tb=short`
- Coverage: `uv run pytest --cov`
- Lint: `uv run flake8 src tests`
- Type check: `uv run mypy src` and/or `uv run pyright`
- Build: `uv build`

### Frontend (from `src/ark_agentic/studio/frontend/`)

- Install: `npm install`
- Dev: `npm run dev` (proxies `/api` and `/chat` to `localhost:8080`)
- Build: `npm run build` — must succeed; `dist/` ships in the wheel via `force-include`
- Lint: `npm run lint`

## Conventions

- Python target 3.10+. Modern type hints (`list[str]`, `X | None`).
- Async-first; pytest is `asyncio_mode = auto` — no `@pytest.mark.asyncio` needed for plain async tests.
- I/O uses `async/await` with `httpx`. Never `requests`.
- Complex data uses `pydantic.BaseModel`. Avoid bare `dict`.
- Package manager is `uv` only. Never `pip` or `poetry`.
- Don't add files under `data/` — gitignored.
- If you touch frontend, run `npm run build` so `dist/` stays consistent for packaging.

## "Done" criteria for any change

1. `uv run pytest -m "not slow"` passes.
2. **Tests for new code exist** per "Testing responsibility" below.
3. If types changed: `uv run mypy src` introduces no new errors.
4. If frontend changed: `npm run build` succeeds.
5. Diff is in scope (see "Scope of change" below).

---

## Behavioral guidelines

> Core principle: **the right amount of design** — not no design, not over-design.

### Design must do (essential)

- **Module boundaries** — clear responsibility, public interface defined as `Protocol`.
- **Data flow** — explicit: where validated, where transformed, where it goes.
- **Error boundaries** — exceptions propagate intentionally, caught at known layers.
- **Core domain** — business-critical logic deserves real modeling.

### Design must avoid (accidental complexity)

- **Speculative generality** — patterns/generics for futures that may never come.
- **Premature layering** — Controller/Service/Repo/DTO around one-line logic.
- **Single-implementer interfaces** — `Protocol` with one impl, kept "for flexibility".
- **Decoupling for aesthetics** — abstraction that makes code harder to follow, not easier to change.

### Decision tests

- Does this abstraction solve a **current concrete problem** (testability, real reuse), or chase an imagined future?
- Does this design make code **easier to delete and change** (good), or does one change ripple everywhere (bad)?
- Would a senior engineer call this overcomplicated? If yes, simplify.

### Operating rules

- **KISS** — function over class unless you genuinely have cohesive state.
- **YAGNI** — don't build what isn't needed now; do leave room at real extension points.
- **Rule of Three** — extract on the third repetition, not the first. Wrong abstraction is worse than duplication.
- **SRP** — one reason to change per module. Pydantic models stay separate from business logic.
- **OCP** — extend via Strategy/Plugin/Hook; don't edit core logic for new features.
- **DIP** — depend on `Protocol`s, inject via `__init__`. No hardcoded `ClassName()` for swappable deps.
- **ISP** — `Protocol` ≤ 5 methods. No god-interfaces.
- **Composition > Inheritance** — inheritance depth ≤ 2.
- **Law of Demeter** — no `a.b.c.method()` chains.
- **Fail fast** — validate at function entry, not in deep call stacks.
- **Type safety** — full type hints on every signature.

### Scope of change

The rule is: **every changed line should trace back to the task**. Deletions
are allowed — and sometimes required — as long as they're in scope.

**Required (you must do these):**

- Remove imports, variables, helpers, and branches that **your** changes
  orphaned. If you replaced function A with B, remove A's now-unused imports
  and any helpers only A called.

**Allowed (do these when applicable):**

- Whatever the task explicitly asks for, including dead-code cleanup.
- Remove pre-existing dead code **only when all of these hold**:
  - it lives in a file you're already editing for this task,
  - it's provably unreferenced (grep the whole repo: zero hits),
  - it's not a public API (not in `__all__`, not exported, not imported elsewhere, not a documented entry point),
  - and you list each deletion explicitly in the PR description so a human can confirm.

**Not allowed (drive-by changes — never do these):**

- "Improving" code adjacent to your change (renaming, reordering, reformatting).
- Refactoring working code outside the task scope.
- Style/lint fixes in files you didn't otherwise have to edit.
- Deleting dead code you stumbled on in a module you're not touching for this task. Instead, list it under "Notes for human reviewer" in the PR.
- Changing something just because you'd write it differently.

When in doubt: smaller diff > "tidier" diff. Match existing style even if you'd do it differently.

### Search before adding

Before writing new code, grep for existing similar logic. If found:
reuse, refactor, or extend. Never copy-paste.

---

## Testing

> Start simple: cover the happy path first, then edges, then errors.
> Don't chase 100% coverage — chase confidence in the change.

### Testing responsibility (matched to task type)

| Task tag | Test responsibility |
|---|---|
| `feature` (new code) | **Required**: happy path + at least one boundary case. Errors if behavior is non-trivial. |
| `bug` (fix)          | **Required**: write a regression test that **fails before** the fix and **passes after**. |
| `refactor`           | **Required**: existing tests pass before and after. Add new tests only if the task asks. |
| `chore` / docs / config | Skip new tests. Run existing tests if code paths could be affected. |

If you can't write a clean test for new code (e.g. it depends on something
hard to mock), that's a **design smell** — fix the design, not the test.

### Test design principles

- **AAA pattern** — Arrange / Act / Assert, in that order, separated by blank lines.
- **One behavior per test** — naming: `test_<function>_<scenario>` (e.g. `test_run_with_empty_input`).
- **Independent & order-free** — no shared mutable state across tests.
- **Fast** — unit tests are seconds, not minutes. Mock external I/O.
- **Specific assertions** — `assert result.status == "success"`, not `assert result`.
  Add a message when context helps: `assert len(items) == 3, f"got {len(items)}"`.
- **Mock the boundary, not the unit** — mock LLM APIs, DBs, network. Never mock the code under test.
- **Async mocks** — use `unittest.mock.AsyncMock` for async dependencies.
- **Fixtures over duplication** — share setup via `@pytest.fixture`, but only once it appears 3+ times (Rule of Three applies here too).

### Test pyramid (write more of the smaller ones)

1. **Unit** (most): single function/method behavior with mocked deps.
2. **Integration** (some): module collaboration, real deps where cheap.
3. **E2E** (few, focused): full user flow — API endpoints via `httpx.AsyncClient` / FastAPI `TestClient`, or full agent chains.

### When unattended (routine runs)

- After implementing, run the right test scope (see `routine` workflow).
- If a new test fails, attempt **one** focused fix. Still failing → mark the
  task ⚠️ partial, leave the test in place (skipped or xfailed with reason),
  continue.
- State assumptions in the PR description rather than guessing silently.
- If a task is ambiguous or risky, mark it ⚠️ partial and leave a note for
  the human reviewer instead of forcing it through.
- Never push to `main` / `master` / `develop`. Only `claude/*` branches.
- Never modify CI configs, `pyproject.toml [build-system]`, `.env*`, or
  anything under `data/` without an explicit task instruction.

### Self-check before committing

1. **Single responsibility?** One reason to change per module/class.
2. **Necessary complexity?** Every abstraction solves a real, current problem.
3. **No premature DRY?** Repetition only extracted if it appeared 3+ times.
4. **Function ≤ 40 lines, nesting ≤ 3 levels?** Otherwise extract or early-return.
5. **Boundary conditions covered?** None / empty / zero / error paths — both in code AND in tests.
6. **Errors fail fast?** Validated at entry, not buried.
7. **Types complete?** No bare `dict`, no `Any` unless justified.
8. **Tests match the task tag?** See "Testing responsibility".
9. **Diff in scope?** Every changed line is either implementing the task or is a direct, required consequence of it (orphan cleanup, regression test). Anything else belongs in a separate PR.

---

For deeper workflows, see:
- `.claude/commands/architect.md` — full architecture pass
- `.claude/commands/review.md` — full code review
- `.claude/commands/test.md` — full test authoring workflow
