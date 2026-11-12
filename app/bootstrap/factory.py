"""Build the FastAPI instance. Middleware, routers, and the page are attached outside."""

from fastapi import FastAPI
from starlette.types import Lifespan

from app.config import get_settings


def build_fastapi(*, lifespan: Lifespan[FastAPI]) -> FastAPI:
    settings = get_settings()
    return FastAPI(
        title=settings.APP_NAME,
        description=settings.APP_DESCRIPTION,
        version=settings.APP_VERSION,
        lifespan=lifespan,
        debug=settings.IS_DEBUG,
    )
