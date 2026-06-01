# Reffie Backend API — Coding Standards & AI Instructions

> **Before every task:** Read `.claude/LESSONS.md` for accumulated lessons from this project.

## Stack

- **Language:** Python 3.13
- **Package manager:** uv
- **Type checker:** pyright (strict mode)
- **Linter/formatter:** ruff
- **Testing:** pytest + pytest-asyncio
- **ORM:** SQLAlchemy 2.0 async
- **Migrations:** Alembic
- **Web framework:** FastAPI
- **Database:** Supabase Postgres (via asyncpg)
- **Task runner:** Taskfile
- **CI/CD:** GitHub Actions
- **Tickets:** Linear (prefer Linear CLI)
- **Feature flags:** Flagsmith
- **Frontend:** React on Vercel (this API is its backend)

## Architecture Preferences

- **Monolith over SOA** — do not split into microservices without explicit instruction.
- **Async tasks:** Use FastAPI background workers for lightweight jobs. AWS Lambda + SQS for heavy/durable async work.
- Always use Python LSP.

## Code Style

### Python version
Use Python 3.12+ style:
```python
# correct
def fn(x: dict[str, int]) -> list[str]: ...

# wrong
from typing import Dict, List
def fn(x: Dict[str, int]) -> List[str]: ...
```

### SQLAlchemy 2.0
```python
# correct
result = await db_session.execute(select(User).where(User.active.is_(True)))
users = result.scalars().all()

# wrong
users = db_session.query(User).filter(User.active == True).all()
```

### Pydantic
```python
# correct
user = User.model_validate(data)

# wrong
user = User(**data)
```

### Sessions / globals
- No multi-file globals.
- Pass `db_session` explicitly through function arguments — never use a module-level session.

### Imports
- Import parent modules, not individual functions (aids mockability in tests):
```python
# correct
import reffie.services.hubspot as hubspot
hubspot.create_contact(...)

# wrong
from reffie.services.hubspot import create_contact
create_contact(...)
```
- Import models from `reffie.models`, not from subfiles.
- All imports at the top of the file.

### Error handling
- No bare `except:` or `except Exception:` without re-raising or specific handling.

### Explicit over implicit
```python
# correct
if items == []:

# wrong
if not items:
```

### Docstrings
Use Sphinx/reST style:
```python
def create_user(email: str, name: str) -> User:
    """
    Create and persist a new user record.

    :param email: The user's email address.
    :param name: The user's display name.
    :returns: The newly created User instance.
    :raises ValueError: If the email is already registered.
    """
```

### Comments
- No obvious inline comments. Comments answer questions a developer would have, not restate the code.
- Correct: `# asyncpg requires the +asyncpg driver prefix in the DSN`
- Wrong: `# connect to database`

## Testing

- **TDD** — write the test first, then the implementation.
- Test assumptions, not just happy paths.
- Run `task lint` after each save.
- Lint the full project before committing.

## Tooling Preferences

- Prefer `gh` (GitHub CLI) and Linear CLI over web UIs.
- Use `task <name>` for all common operations — see `Taskfile.yml`.

## File Layout

```
src/reffie/         # Application source (importable as `reffie`)
  main.py           # FastAPI app factory
  config.py         # Settings via pydantic-settings
  db/               # Database session and base model
  models/           # SQLAlchemy ORM models (import from reffie.models)
  routers/          # FastAPI routers
  services/         # Business logic and external integrations
tests/              # pytest test suite
alembic/            # Migration scripts
Taskfile.yml        # Task runner
pyproject.toml      # Project metadata, deps, tool config
.env.example        # Required env vars (copy to .env)
.claude/LESSONS.md  # Accumulated project lessons
```
