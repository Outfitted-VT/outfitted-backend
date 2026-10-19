# outfitted-backend

FastAPI backend for Outfitted.

## Setup

```bash
python -m venv .venv
source .venv/Scripts/activate   # Windows Git Bash; use .venv\Scripts\Activate.ps1 in PowerShell
pip install -r requirements-dev.txt
cp .env.example .env
```

## Run

```bash
fastapi dev app/main.py
```

- API: http://localhost:8000
- Docs: http://localhost:8000/docs
- Frontend guide: [docs/API.md](docs/API.md)

## Database migrations

Models live in `app/models/`. After adding or changing a model (and importing it in `app/models/__init__.py`):

```bash
alembic revision --autogenerate -m "describe the change"
alembic upgrade head
```

Always review the generated file in `alembic/versions/` before applying it.

## Test

```bash
pytest
```

## Structure

```
app/
├── main.py              # App factory, middleware, error handlers, router mounting
├── core/
│   ├── config.py        # Settings loaded from env / .env
│   └── security.py      # Password hashing, JWT access tokens
├── db/                  # SQLAlchemy Base, engine/session, shared mixins
├── models/              # SQLAlchemy models (database tables)
├── repositories/        # Database queries, one module per model
├── services/            # Business logic, called by endpoints
├── schemas/             # Pydantic request/response models
└── api/
    ├── deps.py          # Shared dependencies (SessionDep, CurrentUser)
    └── v1/
        ├── router.py    # Aggregates v1 endpoint routers
        └── endpoints/   # One module per resource
tests/                   # conftest.py provides an in-memory SQLite db + client
alembic/                 # Migration environment and versions
docs/API.md              # Guide for frontend developers
```

### Layers

Requests flow `api → services → repositories → models`. Each layer only calls the one below it.

| Layer | Does | Doesn't |
|---|---|---|
| `api/` | Parse requests, call services, map errors to HTTP status codes | Query the database or hold business rules |
| `services/` | Business rules; decides when to `commit` / `rollback` | Build SQL queries |
| `repositories/` | `select` / `add` / `flush` for one model | Commit, or know about HTTP or business rules |

### Adding a resource

1. Model in `app/models/<name>.py`, imported in `app/models/__init__.py`
2. Migration: `alembic revision --autogenerate -m "..."`, review it, `alembic upgrade head`
3. Queries in `app/repositories/<name>.py`
4. Rules in `app/services/<name>.py`
5. Schemas in `app/schemas/<name>.py`
6. Endpoints in `app/api/v1/endpoints/<name>.py`, registered in `app/api/v1/router.py`
7. Tests in `tests/`, and update [docs/API.md](docs/API.md)
