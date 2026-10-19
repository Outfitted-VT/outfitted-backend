import mimetypes

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.v1.router import api_router
from app.core.config import settings

# Some OSes (e.g. Windows) don't map .webp, so /media would serve it as octet-stream.
mimetypes.add_type("image/webp", ".webp")

DESCRIPTION = """
Backend API for Outfitted.

All endpoints live under `/api/v1`. Request and response bodies are JSON.

**Authentication:** `POST /auth/login` returns a short-lived access token in the body and
sets a long-lived refresh token as an HttpOnly cookie. Send the access token on protected
endpoints as `Authorization: Bearer <access_token>`; when it expires, `POST /auth/refresh`
returns a new one. In this page, click **Authorize** and paste the access token to try
protected endpoints.

**Errors** always have a `detail` field:
- `4xx` from the API: `{"detail": "Human-readable message"}`
- `422` validation errors: `{"detail": [{"loc": [...], "msg": "...", "type": "..."}]}`
"""

TAGS_METADATA = [
    {"name": "auth", "description": "Sign up, log in, refresh, and log out."},
    {"name": "users", "description": "Your account and public profiles."},
    {"name": "images", "description": "Upload images for fits and avatars."},
    {"name": "fits", "description": "Outfit posts with photos and tagged items."},
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

    # Serve uploaded files from local storage. With S3/R2, MEDIA_BASE_URL points at the
    # bucket or CDN instead and this mount goes unused.
    app.mount("/media", StaticFiles(directory=settings.MEDIA_ROOT, check_dir=False), name="media")

    @app.get("/", tags=["root"])
    def root() -> dict[str, str]:
        return {"message": f"Welcome to {settings.PROJECT_NAME}"}

    return app


app = create_app()
