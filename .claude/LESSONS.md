# Lessons Learned

_Read this file before starting any task. Write new lessons here as you discover them._

---

## 2026-06-02 — HubSpot integration

- **`_apply_deal_fields_to_account` helper avoids `**dict` and create/update duplication**: For upsert logic that must apply the same field mapping to both new and existing ORM instances, write a helper that mutates the object in place (`account.company_name = ...`). This is fully type-safe (no `**dict[str, Any]` unpacking), avoids repeating the mapping twice, and works for both create and update paths.

- **`Account(id=uuid4(), company_name="", ...)` for create before field-fill**: When creating a new SQLAlchemy model that immediately has fields applied via a helper function, initialize required non-nullable columns with empty defaults first (to satisfy pyright's generated `__init__` signature), then call the mutation helper. The empty strings are never visible — the helper overwrites them.

- **Mock three `execute` calls in upsert tests**: `pull_deal` always calls `execute` three times: (1) `select(Account)` upsert check, (2) `delete(Poc)` bulk delete, (3) final `select(Account).options(selectinload(...))`. Tests must configure `mock_session.execute.side_effect` as a list of three mock results. The delete result is unused — `MagicMock()` suffices.

- **`result.scalar_one()` (not `scalar_one_or_none`) for final selectinload**: After `flush()` + `commit()`, re-querying for the freshly inserted row uses `.scalar_one()` — the row is guaranteed to exist at this point. Mocking must match: `final_result.scalar_one.return_value = account`, not `scalar_one_or_none`.

- **httpx is already a project dependency**: `httpx` was included in the scaffold's `pyproject.toml`. Running `uv add httpx` when it already exists is a no-op but safe. Check before adding to avoid duplicate entries.

- **`mock.patch` with `new=AsyncMock(...)` vs `return_value`**: For patching async module-level functions, `mock.patch("path.func", new=AsyncMock(return_value=...))` replaces the function entirely. `mock.patch("path.func") as m; m.return_value = ...` also works but `new=AsyncMock(...)` is more explicit for async patching.

## 2026-06-01 — CRUD endpoints (accounts, checklist, pocs)

- **Async SQLAlchemy requires eager loading everywhere**: accessing a relationship attribute on a persistent object without `selectinload` (or `joinedload`) raises `MissingGreenlet`. Always use `.options(selectinload(...))` on any query that will need relationship data in the response.

- **`server_default` is NOT a Python-side default**: `mapped_column(server_default=sa.text("''"))` sets the DB DDL default. The Python object has `None` until the INSERT is executed and a `refresh()` is done. When creating new ORM objects (especially in test code with mocked sessions), set `done=False`, `note=""`, etc. explicitly — do not rely on server defaults being present on the Python instance.

- **`mapped_column(default=uuid.uuid4)` does NOT set `id` at `__init__` time**: Same issue as server_default. The callable `default=` is invoked when SQLAlchemy generates INSERT SQL, not during `__init__`. Always pass `id=uuid.uuid4()` explicitly when creating ORM objects that will be used before a real DB flush.

- **`AsyncMock()` wraps ALL methods as coroutines**: `AsyncSession.add()` and `AsyncSession.add_all()` are sync methods. When `AsyncMock()` is used as a session mock, calling these generates `RuntimeWarning: coroutine never awaited`. Explicitly set `session.add = MagicMock()` and `session.add_all = MagicMock()` in mock fixtures.

- **`pytest.Generator` does not exist**: Use `collections.abc.Generator` for yield-fixture return type annotations. Similarly use `collections.abc.AsyncGenerator` for async generator return types.

- **`dependency_overrides` with async generator**: To override `get_db_session` (async generator), the override must also be an async generator: `async def fake_db() -> AsyncGenerator[AsyncSession, None]: yield mock_session`. Use `# type: ignore[misc]` on the yield line to suppress the intentional type mismatch (mock vs real session).

- **POST then re-query pattern for responses**: After `add()` + `flush()` + `commit()`, re-query the newly created object with `selectinload` to get a fully loaded instance for the `AccountDetail` response. This adds one query but keeps the response consistent with GET detail.

## 2026-06-01 — Google JWT auth middleware

- **ruff `B008` fires on `Depends()`**: FastAPI's dependency injection uses function calls in default arguments by design. Add `"B008"` to ruff's global `ignore` list for any FastAPI project — it will fire on every route that uses `Depends()`.

- **pyright strict + unstubbed libraries**: `reportMissingTypeStubs = false` suppresses the import warning, but `reportUnknownMemberType` still fires when calling functions from the unstubbed module. Suppress at the specific call site with `# pyright: ignore[reportUnknownMemberType]` rather than a blanket `# type: ignore`.

- **`HTTPBearer(auto_error=False)` for 401 on missing tokens**: FastAPI's default `HTTPBearer()` returns 403 when no Bearer token is present. Use `auto_error=False` and check `if credentials is None` manually to return 401 consistently.

- **`reportUnusedFunction` on FastAPI route functions with `_` prefix**: pyright strict flags `_private_fn` as unused if never explicitly called. FastAPI route functions are consumed by the decorator, not called directly — avoid the `_` prefix on route handlers.

- **`conftest.py` must set env vars at module level, not in fixtures**: `reffie.config` instantiates `Settings()` at import time. By the time a fixture runs, the module is already imported. Set `os.environ.setdefault(...)` at the top of `conftest.py` (outside any function) so values are present before pytest collects test modules.

- **Mock target for parent-module imports**: When auth.py does `import google.oauth2.id_token as google_id_token`, the mock target is `"google.oauth2.id_token.verify_oauth2_token"` (the canonical module path), not `"reffie.auth.google_id_token.verify_oauth2_token"`. Both work because the alias refers to the same module object.

## 2026-06-01 — Initial model scaffold

- **ruff `ANN101`/`ANN102` removed**: These rules no longer exist in ruff 0.5+. Remove them from `pyproject.toml` `[tool.ruff.lint] ignore` list or ruff will warn on every run.

- **SQLAlchemy `Uuid` vs `UUID`**: Use `sa.Uuid(as_uuid=True)` (capital U, no `G`) — the SQLAlchemy 2.0 dialect-agnostic UUID type. The legacy `sa.UUID` and `postgresql.UUID` both still work but `sa.Uuid` is the idiomatic 2.0 choice.

- **`ARRAY` server default**: For Postgres `text[]`, the correct `server_default` string is `"'{}'"` (the Postgres empty-array literal). `"{}"` without quotes is invalid SQL.

- **`func.now()` in `server_default`**: Pass `sa.text("now()")` for `server_default`, not `func.now()`. The stubs for `server_default` accept `str | TextClause | FetchedValue | ColumnDefault`; `Function[datetime]` from `func.now()` does not satisfy that type. Use `func.now()` for `onupdate` (typed as `Any`).

- **Cross-model relationships with `TYPE_CHECKING`**: Use `from __future__ import annotations` + `TYPE_CHECKING` imports for relationship targets. SQLAlchemy 2.0 resolves mapper references from the registry at configuration time, so the runtime non-import is fine. Pyright is satisfied because `TYPE_CHECKING` makes the type visible at analysis time.

- **Alembic autogenerate requires a live DB**: `alembic revision --autogenerate` tries to connect to compare schemas. Without a database it fails. Write migrations manually when no DB is available.

- **`reffie.config` (module-level `settings`) is not loaded during tests** as long as `reffie.db.session` is not imported. The health test imports only `reffie.main` → `reffie.routers.health`, so no `.env` file is needed for the test suite to pass.
