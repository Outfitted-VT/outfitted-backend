from fastapi import APIRouter

from app.api.v1.endpoints import (
    auth,
    detections,
    fits,
    health,
    images,
    impact,
    sizing,
    tryons,
    users,
)

api_router = APIRouter()
api_router.include_router(health.router, prefix="/health", tags=["health"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(images.router, prefix="/images", tags=["images"])
api_router.include_router(fits.router, prefix="/fits", tags=["fits"])
api_router.include_router(tryons.router, prefix="/tryons", tags=["try-on"])
api_router.include_router(detections.router, prefix="/detections", tags=["detection"])
api_router.include_router(sizing.router, prefix="/sizing", tags=["sizing"])
api_router.include_router(impact.router, prefix="/impact", tags=["impact"])
