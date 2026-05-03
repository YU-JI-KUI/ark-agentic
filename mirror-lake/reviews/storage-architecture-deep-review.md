# Top-down architectural review — `feat/storage-abstraction-sqlite`

**Goal of this review** (per user prompt): audit layering, responsibility
separation, protocol minimality, consumer cleanliness — assuming **no
backward-compatibility constraints**. Old data may be dropped.

---

## TL;DR

The Repository protocol layer itself is well-shaped. The **layering on top
of it is not yet honoured by the consumers**: domain code (`dream.py`,
`proactive_service.py`, `notifications` API, `lifespan`) and the Studio
authz module reach around the protocol straight into file-only classes
(`SessionStore`, `TranscriptManager`, `NotificationStore`) or into
hand-rolled SQLAlchemy code. Under `DB_TYPE=sqlite` these bypasses cause
data loss / silent breakage.

The persistence DTO (`SessionStoreEntry`) leaks file-system semantics
(`session_ref`) and the file-only persistence classes leak as a public
API of the package. With "no backward compat" we can collapse and clean
these up.

---

## Current layer map

```
┌──────────────────────────────────────────────────────────────────┐
│ HTTP / API   (api/, studio/api/, runner-driven SSE)             │
└──┬──────────────────────────────────────────┬────────────────────┘
   │                                          │   (multiple paths
   ▼                                          │    bypass managers)
┌──────────────────────────────────────────────┐
│ Domain layer                                 │
│ ✅ SessionManager                            │
│ ✅ MemoryManager                             │
│ ❌ no NotificationManager / AgentStateMgr    │
│ ❌ StudioUserStore lives outside the layer   │
│ ❌ dream.py reaches around managers          │
└──┬───────────────────────────────────────────┘
   │ should be the only seam
   ▼
┌──────────────────────────────────────────────┐
│ Storage Protocol layer (core/storage/protocols/) │
│ ✅ SessionRepository                         │
│ ✅ MemoryRepository                          │
│ ✅ AgentStateRepository                      │
│ ✅ NotificationRepository                    │
│ ✅ Cache                                     │
│ ❌ no StudioUserRepository                   │
└──┬───────────────────────────────────────────┘
   │
   ▼
┌──────────────────────────────────────────────┐
│ Backend implementations                      │
│ - File* (wrap legacy file classes)           │
│ - Sqlite* (use shared engine)                │
└──┬───────────────────────────────────────────┘
   │
   ▼
┌──────────────────────────────────────────────┐
│ Infrastructure                               │
│ - core/db/{engine, base, models, config}     │
│ - core/persistence.py (TranscriptManager,   │
│   SessionStore — file-only, leaks public)   │
│ - services/notifications/store.py           │
│   (NotificationStore — file-only, leaks)    │
│ - StudioUserStore (own engine resolution)   │
└──────────────────────────────────────────────┘
```

---

## 1. Responsibility separation — **half done**

### What's clean

- `MemoryManager` (`core/memory/manager.py`) is a textbook delegation:
  3 methods, each one async-forward to `MemoryRepository`. Owns no
  storage state. **Use this as the model for the others.**
- `SessionManager` (after the previous fix in this PR) now also delegates
  every storage operation to `SessionRepository`.
- The Protocol layer is small and well-bounded — every protocol has
  ≤ 5 methods (after `list_all_sessions` was added) and is
  `@runtime_checkable`.

### What still leaks the abstraction

#### Domain code instantiating file-only classes directly

| File | Bypass | Effect under `DB_TYPE=sqlite` |
|---|---|---|
| `core/memory/dream.py:112-115` | `SessionStore(sessions_dir)` + `TranscriptManager(sessions_dir)` inside `read_recent_sessions` | Reads nothing — sessions live in SQLite |
| `core/memory/dream.py:175-177` | `SessionStore(sessions_dir)` inside `should_dream` | Always returns False under SQLite |
| `app.py:98` (lifespan) | `NotificationStore(...)` for `JobManager` wiring | Job notifications go to disk, never to SQLite |
| `api/notifications.py:152` | `NotificationStore(...)` per-agent cache | API serves disk only |
| `services/jobs/proactive_service.py:124` | `NotificationStore(...)` | Job-produced notifications go to disk only |

These are all **production-broken under `DB_TYPE=sqlite`** because the
respective writes/reads silently target the wrong storage. They were
hidden by the previous SessionManager dual-storage bug (also caught) plus
the `:memory:` tests that don't exercise these paths.

#### Asymmetric domain manager coverage

| Domain | Domain Manager | Protocol | Status |
|---|---|---|---|
| Sessions | ✅ `SessionManager` | `SessionRepository` | clean (post-fix) |
| Memory | ✅ `MemoryManager` | `MemoryRepository` | clean |
| Notifications | ❌ none — `NotificationStore` doubles as both | `NotificationRepository` | wired only on the **read** side; producers bypass it |
| Agent State | ❌ none — `AgentStateRepository` used directly by callers | `AgentStateRepository` | acceptable (3 methods, no real domain logic above the repo) |
| Studio users | ❌ `StudioUserStore` (outside the abstraction) | none | needs `StudioUserRepository` |

For Notifications the right answer isn't "add a NotificationManager"
just for symmetry — the domain logic above the protocol is empty. The
right answer is: **inject `NotificationRepository` directly at the API
and job layer**, drop the standalone `NotificationStore`.

For Agent State the same applies — the protocol IS the domain interface.
No manager needed.

For Studio users we need the protocol; the SQL layer in `authz_service`
is doing exactly what a Repository should do.

---

## 2. Inside-each-layer cleanliness

### `SessionStoreEntry` (data model leak)

Defined in `core/persistence.py` (a file-backend module) and carries:

```python
session_ref: str | None = None      # file-system path
session_file: str | None  (alias)   # backward-compat alias
to_dict() / from_dict() emit "sessionFile" key for studio frontend
```

`session_ref` is meaningless under SQLite — it's a literal file path on
disk. With "no backward compat" this should go. The DTO should live in
`core/storage/entries.py` (or just `core/storage/protocols/_dtos.py`),
not inside the file-backend module.

### File-only persistence classes leak as public API

`TranscriptManager`, `SessionStore`, `NotificationStore` are imported by
five different modules outside the Repository implementations. They were
intended to be private to the file backend. With no backward compat, the
right move is to **inline them as private helpers inside `FileXxxRepository`**
and delete the standalone classes — that closes the leak and removes a
whole layer.

### `MemoryCache` filed under `backends/file/`

`MemoryCache` is in-process memory, not file. Its directory placement is
incorrect. Should be either `backends/memory/` or just `core/storage/cache.py`.
Cosmetic but confusing.

### `StudioUserStore` duplicates engine wiring

`studio/services/authz_service.py` re-implements `_normalize_async_url`,
`_sqlite_path_from_url`, `_create_engine` — already in `core/db/engine.py`.
Has its own `_resolve_engine_for_singleton` that picks between
`STUDIO_DATABASE_URL` and the central engine. Two engines for two
schemas in the same DB file — confusing.

### `_TranscriptManager._get_session_file` is private but called from outside

`SessionManager.create_session` (pre-fix) and other consumers reached
into `TranscriptManager._get_session_file(...)` to compute a file path
for the `session_ref` field. Naming says private; usage says public.
Drops out naturally once `session_ref` goes away.

---

## 3. Repository protocol minimality

### Per-protocol method count

| Protocol | Methods | Verdict |
|---|---|---|
| `SessionRepository` | 11 (after `list_all_sessions`) | **Edge of "god interface"** — should split |
| `MemoryRepository` | 4 | Clean |
| `AgentStateRepository` | 3 | Clean |
| `NotificationRepository` | 3 | Clean |
| `Cache` | 4 | Clean |

`SessionRepository` is doing too much. Possible split:

```
SessionMessagesRepository:    append_message, load_messages,
                              get_raw_transcript, put_raw_transcript

SessionMetaRepository:        create, update_meta, load_meta,
                              list_session_ids, list_all_sessions,
                              delete, finalize
```

That's two ≤6-method protocols. But the cohesion is real: every caller
that touches messages also touches meta. Keeping them together is a
defensible KISS decision. **Recommendation: leave together for now; split
only if a caller appears that genuinely uses one without the other.**

### Cross-protocol consistency

The `limit/offset` semantics are now consistent (after the previous
docstring fix). Good.

The `list_session_metas` method is **missing** — `dream.py` needs to
list sessions with their `updated_at` for filtering. Currently the only
way to do this through the protocol is `list_session_ids` + N
`load_meta` calls (N+1). Adding `list_session_metas(user_id, limit, offset)`
returning `list[SessionStoreEntry]` is the right shape.

### Protocol DI

Factories take `sessions_dir | None, engine | None` — fine for now.
Future cleanup: a tagged `BackendConfig` union once a third backend
arrives.

---

## 4. Consumers — concrete refactor list

The user said "consumers can be refactored together". Here's the
minimal-but-complete list:

### `core/memory/dream.py`

- `read_recent_sessions(user_id, sessions_dir, since_ts, token_budget)` →
  `read_recent_sessions(user_id, session_repo, since_ts, token_budget)`.
- `should_dream(state_repo, user_id, sessions_dir, ...)` →
  `should_dream(state_repo, session_repo, user_id, ...)`.
- Drop the inline `from ..persistence import SessionStore, TranscriptManager`.
- Add `list_session_metas` to `SessionRepository` so we don't N+1.

### `app.py` (lifespan)

- Replace `NotificationStore(base_dir=get_notifications_base_dir())` with
  `build_notification_repository(base_dir=..., engine=app.state.db_engine)`.
- Pass the repository (not the store) to the JobManager.

### `api/notifications.py`

- `_get_agent_store(request, agent_id)` → `_get_agent_repo(request, agent_id)`.
  Build `NotificationRepository` via factory, cache on `app.state` keyed
  by agent. Type the variable as `NotificationRepository`.

### `services/jobs/proactive_service.py`

- Constructor accepts `notification_repo: NotificationRepository` instead
  of constructing a `NotificationStore` internally.
- Drop the `from ..notifications.paths import get_notifications_base_dir`
  import — repo is fully wired by the caller.
- `notification_store` property → `notification_repo` property.

### `services/jobs/scanner.py`, `services/jobs/manager.py`, `services/jobs/base.py`

- Type names everywhere change from `NotificationStore` →
  `NotificationRepository` (Protocol).
- `Job.notification_store` → `Job.notification_repo` (rename + type
  change).

### `core/runner.py` (call site of `should_dream`)

- Pass `self.session_manager.repository` instead of `sessions_dir`.

### `core/persistence.py`

- Drop `TranscriptManager` and `SessionStore` (move internals into
  `FileSessionRepository` as private helpers).
- Keep `SessionStoreEntry` (will move to `core/storage/entries.py` in
  the cleanup phase) and JSONL validation utilities (`SessionHeader`,
  `MessageEntry`, `RawJsonlValidationError`, `serialize_message`,
  `deserialize_message`).

### `services/notifications/store.py`

- Delete the standalone `NotificationStore` class. Move its file I/O
  logic into `FileNotificationRepository` as private helpers.
- Keep `services/notifications/models.py` (Notification, NotificationList).

### `studio/services/authz_service.py`

- Add `StudioUserRepository` protocol with the methods Studio actually
  needs (list_users_page, get_user, ensure_user, upsert_user, delete_user).
- Move `StudioUserStore` body into `SqliteStudioUserRepository`.
- Drop the duplicated `_normalize_async_url` / `_create_engine` —
  reuse `get_async_engine`.
- Either provide a `FileStudioUserRepository` (small JSON file) OR
  declare Studio SQLite-only and raise loudly under `DB_TYPE=file`
  with a clear error.
- Keep the singleton accessor (`get_studio_user_store()`) but route
  it through the factory so it picks the right backend.

### `scripts/migrate_file_to_sqlite.py`

- Keep using `TranscriptManager` / `SessionStore` / `NotificationStore`?
  → No, they're being deleted. Either:
  - inline file-reading code into the migration script (acceptable —
    it's the source-of-truth file format),
  - OR construct `FileXxxRepository` instances and read through them.

  The second is cleaner and lets the migration script piggyback on the
  same file-format knowledge.

---

## 5. "No backward compat" cleanups

With BC dropped:

1. **Drop `session_ref` and the `session_file` property on
   `SessionStoreEntry`.** No backend needs to round-trip a file path.
   The to_dict() / from_dict() get cleaner (no `sessionFile` key).
2. **Move `SessionStoreEntry` out of `core/persistence.py`** into
   `core/storage/entries.py` (or `core/storage/protocols/_dtos.py`).
3. **Delete `TranscriptManager` / `SessionStore` / `NotificationStore`
   public exports.** Inline as private helpers inside file backends.
4. **Move `MemoryCache`** to `core/storage/backends/memory/cache.py`
   (or just `core/storage/cache_inproc.py`).
5. **Drop `STUDIO_DATABASE_URL` legacy env path.** Studio rides on the
   central engine.
6. **`core/persistence.py` shrinks to JSONL validation + DTO.**

---

## Recommended commit order

1. **(this doc)** — architectural review for the record.
2. **Fix domain bypasses** (P0 production bugs):
   - dream.py, app.py, api/notifications.py, proactive_service.py,
     scanner.py, manager.py, base.py, runner.py.
   - Add `list_session_metas` to `SessionRepository` + both backends.
3. **Collapse file-only persistence classes**:
   - Inline `TranscriptManager` / `SessionStore` into `FileSessionRepository`.
   - Inline `NotificationStore` into `FileNotificationRepository`.
   - Drop the public exports. Update migration script.
4. **Studio users into the abstraction**:
   - Add `StudioUserRepository` protocol + SQLite backend.
   - Refactor `authz_service` to depend on it.
5. **DTO cleanup**:
   - Remove `session_ref` from `SessionStoreEntry`.
   - Move `SessionStoreEntry` to `core/storage/entries.py`.
   - Move `MemoryCache` out of `backends/file/`.

After all five, the layering is:

```
API  →  Domain managers / direct repo usage  →  Protocols  →  Backends  →  Engine/FS
```

with each arrow being the only allowed direction of dependency, and
each layer having a single, clearly-defined responsibility.
