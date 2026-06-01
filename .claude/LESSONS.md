# Lessons Learned

_Read this file before starting any task. Write new lessons here as you discover them._

---

## 2026-06-01 — Initial model scaffold

- **ruff `ANN101`/`ANN102` removed**: These rules no longer exist in ruff 0.5+. Remove them from `pyproject.toml` `[tool.ruff.lint] ignore` list or ruff will warn on every run.

- **SQLAlchemy `Uuid` vs `UUID`**: Use `sa.Uuid(as_uuid=True)` (capital U, no `G`) — the SQLAlchemy 2.0 dialect-agnostic UUID type. The legacy `sa.UUID` and `postgresql.UUID` both still work but `sa.Uuid` is the idiomatic 2.0 choice.

- **`ARRAY` server default**: For Postgres `text[]`, the correct `server_default` string is `"'{}'"` (the Postgres empty-array literal). `"{}"` without quotes is invalid SQL.

- **`func.now()` in `server_default`**: Pass `sa.text("now()")` for `server_default`, not `func.now()`. The stubs for `server_default` accept `str | TextClause | FetchedValue | ColumnDefault`; `Function[datetime]` from `func.now()` does not satisfy that type. Use `func.now()` for `onupdate` (typed as `Any`).

- **Cross-model relationships with `TYPE_CHECKING`**: Use `from __future__ import annotations` + `TYPE_CHECKING` imports for relationship targets. SQLAlchemy 2.0 resolves mapper references from the registry at configuration time, so the runtime non-import is fine. Pyright is satisfied because `TYPE_CHECKING` makes the type visible at analysis time.

- **Alembic autogenerate requires a live DB**: `alembic revision --autogenerate` tries to connect to compare schemas. Without a database it fails. Write migrations manually when no DB is available.

- **`reffie.config` (module-level `settings`) is not loaded during tests** as long as `reffie.db.session` is not imported. The health test imports only `reffie.main` → `reffie.routers.health`, so no `.env` file is needed for the test suite to pass.
