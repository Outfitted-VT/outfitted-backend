from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.router import api_router
from app.core.config import settings

DESCRIPTION = """
Backend API for Outfitted.

All endpoints live under `/api/v1`. Request and response bodies are JSON.

**Errors** always have a `detail` field:
- `4xx` from the API: `{"detail": "Human-readable message"}`
- `422` validation errors: `{"detail": [{"loc": [...], "msg": "...", "type": "..."}]}`
"""

TAGS_METADATA = [
    {"name": "auth", "description": "Sign up and (soon) log in."},
    {"name": "health", "description": "Service and database status."},
]


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.PROJECT_NAME,
        version=settings.VERSION,
        description=DESCRIPTION,
        openapi_tags=TAGS_METADATA,
        openapi_url=f"{settings.API_V1_PREFIX}/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # Same shape as FastAPI's default 422, minus "input", which would echo back passwords.
        errors = [{k: v for k, v in error.items() if k != "input"} for error in exc.errors()]
        return JSONResponse(status_code=422, content=jsonable_encoder({"detail": errors}))

    app.include_router(api_router, prefix=settings.API_V1_PREFIX)

    @app.get("/", tags=["root"])
    def root() -> dict[str, str]:
        return {"message": f"Welcome to {settings.PROJECT_NAME}"}

    return app


app = create_app()
