# Lessons Learned

_Read this file before starting any task. Write new lessons here as you discover them._

---

## 2026-06-04 — HubSpot association API version for reads

- **Always use v4 (`/crm/v4/objects/{type}/{id}/associations/{toType}`) for association reads, never v3.** The v3 associations endpoint can silently return `HTTP 200 + {"results": []}` in cases where v4 returns the correct data — even with the correct scopes granted. This was observed on the `deals→quotes` association: v3 returned empty, v4 returned the quote. Every working association function in this codebase uses v4 (`get_deal_contact_ids`, `get_deal_company_id`).

- **v4 response uses `toObjectId`, not `id`.** Parse `r["toObjectId"]` from v4 results. v3 used `r["id"]` — these are NOT interchangeable.

- **Object reads and batch reads stay on v3.** `GET /crm/v3/objects/{type}/{id}` (single object fetch) and `POST /crm/v3/objects/{type}/batch/read` (batch property fetch) are object-read endpoints, not association endpoints — these are unaffected by the v3/v4 association distinction and should remain as v3.

---

## 2026-06-03 — Auto-account-creation robustness

- **Numeric IDs serialised as strings sort lexicographically by default** (`'10' < '9'`). When sorting on string-typed numeric IDs, parse to int with a string fallback: `try (0, int(raw)) except (1, str(raw))`. This gives numeric ordering for normal HubSpot IDs and a stable fallback for any non-numeric edge cases.

- **HubSpot deal-to-contact associations can include deleted contacts**; fetching a deleted contact returns 404. Always wrap per-contact fetches in `try/except HubSpotNotFoundError` and skip with a `logger.warning` — don't let one missing contact abort an entire deal sync. Use a for-loop with `continue`, not a list comprehension.

- **In background tasks that touch the DB, wrap the entire function body in `try/except` for both `SQLAlchemyError` and `HubSpotAPIError/HubSpotNotFoundError`**. The inner per-call catches handle recoverable errors (letting processing continue for other quotes/contacts). The outer catch is a safety net for anything that slips through. Never catch bare `Exception` — let other bugs surface visibly in logs.

---

## 2026-06-03 — Railway/Nixpacks TOML startCommand quoting

- **Do NOT use shell-style nested quotes inside TOML startCommand strings.** Railway and Nixpacks parse these strings as TOML before passing them to a shell. `--forwarded-allow-ips='*'` inside a TOML double-quoted string is passed to uvicorn with the literal quote characters, causing uvicorn to receive `'*'` (with apostrophes) rather than `*`. Worse, `--forwarded-allow-ips=\'*\'` inside a TOML single-quoted (literal) string is **invalid TOML** — literal strings cannot contain single quotes, and backslash is not an escape character in them; the string terminates at the first `'`, breaking the parse entirely. Use bare unquoted values: `--forwarded-allow-ips=*`. When `=` joins the flag and value as a single token, no shell glob expansion occurs.

---

## 2026-06-03 — HubSpot webhook signature versions

- **HubSpot supports three signature versions — always handle all three on the same endpoint:**
  - V1: `SHA-256(client_secret + request_body)`, hex-encoded, header `X-HubSpot-Signature`
  - V2: `SHA-256(client_secret + method + uri + request_body)`, hex-encoded, header `X-HubSpot-Signature` + `X-HubSpot-Signature-Version: v2`
  - V3: `base64(HMAC-SHA256(key=client_secret, msg=method + uri + body + timestamp))`, header `X-HubSpot-Signature-V3` + `X-HubSpot-Request-Timestamp` (5-minute replay window)
  - Dispatch by which headers are present: V3 if both `X-HubSpot-Signature-V3` and `X-HubSpot-Request-Timestamp` present, else V1/V2 via `X-HubSpot-Signature`.
  - Legacy private apps typically send V1 or V2. OAuth apps send V3.

- **Behind a reverse proxy (Railway), start uvicorn with `--proxy-headers --forwarded-allow-ips='*'`**: Without this, `str(request.url)` returns `http://` instead of `https://`, breaking V3 signature verification because the URI in the computed hash won't match what HubSpot signed.

---

## 2026-06-02 — GitHub Actions + Railway deployment

- **`uv sync --locked` requires `uv.lock` committed to git**: CI runs `uv sync --locked` which verifies the lockfile matches `pyproject.toml`. If `uv.lock` is absent or gitignored, CI fails at the install step. Always commit `uv.lock`.

- **Railway CLI: `npm i -g @railway/cli` is more reliable in GitHub Actions than `bash <(curl ...)`**: The curl-pipe-bash install (`cli.new`) requires a tty and fails with exit 127 in CI. `npm` is always present on `ubuntu-latest` runners.

- **Railway services must be created in the project before `railway up --service <name>` can deploy to them**: First-time deploys need either an Empty Service pre-provisioned in the Railway UI with the matching service name, OR omit `--service` to let Railway create one — but that creates a new service per deploy. Always pre-provision the named service.

- **The `.github/workflows/` folder must be at the git root of the repository pushed to GitHub, not a parent directory**: If the backend project lives in a subdirectory of a larger working tree, ensure the workflow file is committed inside that subdirectory (making it the git root for the GitHub repo) before the first push.

- **GitHub Actions cache failures (400 on cache save/restore) are infrastructure noise**: These appear as warnings in the `setup-uv` step but do not fail the job. Ignore them unless the job itself fails.

- **Railway Nixpacks does not reliably auto-detect uv**: Even though Nixpacks added uv support in 2024, detection is version-dependent. Provide an explicit `nixpacks.toml` that installs uv via the install script (`curl -LsSf https://astral.sh/uv/install.sh | sh`) and calls `uv sync --locked --no-dev`. This is belt-and-suspenders but avoids mysterious build failures on Railway.

- **Run Alembic migrations as part of `startCommand`**: Include `alembic upgrade head &&` before starting uvicorn in `railway.toml`'s `startCommand`. This makes deploys self-healing — any migration committed alongside code is applied on the next deploy. If the migration fails, Railway rolls back to the previous image. Never assume the DB schema is already up to date.

- **GitHub Actions deploy job must be gated on `github.event_name == 'push'`**: The `if:` condition `github.event_name == 'push' && github.ref == 'refs/heads/main'` prevents the deploy job from running on PRs. Without the `event_name` check, a PR from a branch named `main` (or targeting `main`) could trigger Railway deployment. Always gate deploys on both the event type and the ref.

- **Project in a subdirectory requires `defaults.run.working-directory`**: When the Python project lives in a subdirectory of the git repo (e.g. `reffie-onboarding-api/`), add `defaults: run: working-directory: reffie-onboarding-api` to the workflow. All `uv run`, `ruff`, `pyright`, and `railway up` commands then resolve paths relative to the project root without per-step `cd`. `railway.toml` and `nixpacks.toml` belong in the project subdirectory, not the git root.

---

## 2026-06-02 — HubSpot webhook integration

- **HubSpot webhook signature verification (HMAC-SHA256)**: HubSpot signs requests with the V3 signature scheme. The expected signature is `SHA-256(client_secret + HTTP_method + full_URI + raw_body)` as a hex digest, sent in the `X-HubSpot-Signature-V3` header. Always compare with `hmac.compare_digest` (constant-time). Return 401 on missing or invalid signature. The secret is the HubSpot app's **client secret** (not the portal API key) — store it in `HUBSPOT_WEBHOOK_SECRET`.

- **HubSpot deal stage IDs are pipeline-specific internal identifiers, not labels**: The `dealstage` property value sent in webhook events is an opaque internal ID like `"closedwon"` or `"8b76c620-..."`, not a human-readable label. Labels vary by portal and pipeline. Store the recognised Closed Won stage IDs as a configurable list (`HUBSPOT_CLOSED_WON_STAGE_IDS`, comma-separated in the env) so new pipelines can be added without code changes.

- **Quote line items require a two-step fetch**: There is no single endpoint that returns a quote's line items with properties. Step 1: `GET /crm/v3/objects/quotes/{id}/associations/line_items` — returns a list of `{id}` objects (NOT `toObjectId`, unlike the v4 associations API). Step 2: `POST /crm/v3/objects/line_items/batch/read` with `{"properties": ["name","sku","quantity","price"], "inputs": [{"id": "..."}]}` — returns the full line item objects. Skip step 2 and return `[]` early if the associations list is empty.

- **Webhook handlers must return 200 immediately — never block on side effects**: HubSpot retries webhooks that don't receive a 2xx response quickly. Use FastAPI `BackgroundTasks` to dispatch all processing (DB writes, further API calls) after returning `{"status": "ok"}`. Background tasks open their own `AsyncSessionLocal()` session (same as the writeback pattern) because the request-scoped session is already closed when the task runs.

- **pydantic-settings raises before field_validators can run for list fields from env**: For `list[str]` fields, `EnvSettingsSource` calls `decode_complex_value` (which does `json.loads`) at the *source* level — the JSON decode exception is re-raised as `SettingsError` before Pydantic ever runs `@field_validator`. The fix is NOT a `field_validator` alone. Override `decode_complex_value` in subclasses of both `EnvSettingsSource` and `DotEnvSettingsSource` to fall back to comma-separated parsing on `ValueError`, then inject both via `settings_customise_sources`. `@field_validator` can still remain as a fallback for values that bypass the source (e.g. direct `Settings(...)` instantiation), but it is NOT what saves the env-var case.

---

## 2026-06-02 — HubSpot Company associations

- **Fetching a deal's associated company requires a separate API call**: HubSpot's deal object does not embed the company; it must be retrieved via `/crm/v4/objects/deals/{deal_id}/associations/companies`. An empty `results` array means no company is associated (not a 404). The v4 response contains `toObjectId` per associated object — take `results[0]["toObjectId"]` for the primary company. Company properties are then fetched separately via `/crm/v3/objects/companies/{company_id}?properties=...`.

- **`dict` invariance requires `Mapping` for read-only function params**: When a function only reads from a dict parameter, declare it as `Mapping[K, V]` (from `collections.abc`) rather than `dict[K, V]`. `dict` is invariant — `dict[str, str]` is NOT assignable to `dict[str, str | None]` in pyright strict mode. `Mapping` is covariant in its value type, so `Mapping[str, str]` IS assignable to `Mapping[str, str | None]`.

## 2026-06-02 — Async SQLAlchemy session lifecycle

- **Async SQLAlchemy + FastAPI: ALWAYS set `expire_on_commit=False` on the session factory.** Default `expire_on_commit=True` marks every attribute as expired after `session.commit()`. Any subsequent attribute access (e.g. Pydantic's `model_validate`) triggers a lazy-load that cannot run synchronously in an async context — this raises `MissingGreenlet: greenlet_spawn has not been called`. Fix: `async_sessionmaker(..., expire_on_commit=False)`. Combine with eager loading (`selectinload`) for relationships so they are populated before the session boundary.

- **Re-load after commit to get DB-side computed values**: Even with `expire_on_commit=False`, the in-memory object retains pre-commit values for server-side columns like `updated_at` (set via `onupdate=func.now()`). After `commit()`, re-query via the existing `_load_account_detail` helper (or a fresh `select`) to reflect the actual DB state in the response. This mirrors the create-then-re-query pattern already used in `create_account`.

## 2026-06-02 — CORS

- **FastAPI does not handle CORS by default**: OPTIONS preflight requests return 405 unless `CORSMiddleware` is registered. Always add `CORSMiddleware` before mounting routers (middleware is applied in reverse registration order, so earlier = outer). Configure allowed origins via env var for flexibility across local/staging/production — use a `@field_validator(mode='before')` in Settings to split a comma-separated `CORS_ORIGINS` string into a `list[str]`.

## 2026-06-02 — Database / migrations

- **JSONB columns in SQLAlchemy 2.0**: Import `JSONB` from `sqlalchemy.dialects.postgresql` (not `sqlalchemy`). Annotate as `Mapped[dict[str, Any]]` and use `server_default=sa.text("'{}'::jsonb")` — the `::jsonb` cast is required, same as `::varchar[]` for ARRAY. In Python, `Any` must be imported from `typing` at the top level (not under `TYPE_CHECKING`) since it appears in runtime-evaluated annotations unless `from __future__ import annotations` is present.

- **Alembic autogenerate picks up unrelated tables when the DB has other apps**: If the Supabase schema contains tables from other projects, autogenerate will try to drop them. Always read the generated migration and strip any `op.drop_table` / `op.drop_index` calls that don't belong to this app before running `alembic upgrade head`.

- **Postgres ARRAY columns need explicit cast in server_default**: Use `sa.text("'{}'::varchar[]")` not `sa.text("'{}'")`— the latter produces malformed SQL that Postgres rejects. The explicit `::varchar[]` cast tells Postgres the type of the empty array literal unambiguously.

## 2026-06-02 — HubSpot write-back & background tasks

- **Background tasks open their own DB session**: FastAPI runs background tasks after the HTTP response is sent. The request-scoped `AsyncSession` is already closed by then. Never pass the request's `db_session` to a background task — instead, open a fresh session inside the task function using `AsyncSessionLocal()`. Accepting `account_id: UUID` (not `account: Account`) forces the task to re-fetch state from a live session.

- **Mock `AsyncSessionLocal` by patching at the source**: `writeback.py` imports `reffie.db.session as db_session_module` and calls `db_session_module.AsyncSessionLocal()`. Patching `reffie.db.session.AsyncSessionLocal` works because the module alias and the canonical path refer to the same attribute on the same module object. The mock must behave as an async context manager: set `mock_session.__aenter__ = AsyncMock(return_value=mock_session)` and `mock_session.__aexit__ = AsyncMock(return_value=False)`.

- **Background tasks fire during test `await client.post(...)` — must be mocked in router tests**: When a router adds a background task, it runs inline during the ASGI call in tests (Starlette's `BackgroundTasks` run before the client receives the response). If the background task opens a real DB connection, integration-only tests without a real DB will crash. Add an `autouse=True` fixture that patches `reffie.hubspot.writeback.sync_stage_to_hubspot` with `AsyncMock()` in any router test file that does not want to test write-back side effects.

- **Read-only field guard in `update_deal_properties`**: `kickoff_call_date` is permanently read-only from the HubSpot side — any attempt to write it would silently corrupt the value. Added an explicit `if "kickoff_call_date" in properties: raise ValueError(...)` guard at the top of `update_deal_properties`. This makes the invariant enforced in code, not just documented.

- **`N812` ruff rule fires on `settings as _SETTINGS`**: Ruff's N812 rule disallows importing a lowercase name as a non-lowercase alias. Use `settings as _settings` (all-lowercase with underscore) in test files; constants in test helpers should be all-caps only when they're true literals, not imported singleton instances.

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
