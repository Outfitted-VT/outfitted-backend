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
├── main.py              # App factory, middleware, router mounting
├── core/config.py       # Settings loaded from env / .env
├── api/v1/
│   ├── router.py        # Aggregates v1 endpoint routers
│   └── endpoints/       # One module per resource
└── schemas/             # Pydantic request/response models
tests/                   # conftest.py provides an in-memory SQLite db + client
alembic/                 # Migration environment and versions
```

Keep [docs/API.md](docs/API.md) in sync when endpoints change.

To add a resource: create `app/api/v1/endpoints/<name>.py` with an `APIRouter`, add its schemas under `app/schemas/`, and register it in `app/api/v1/router.py`.
