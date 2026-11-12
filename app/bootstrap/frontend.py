"""Serve the control tower. API routes are registered before these routes."""

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import BASE_DIR

_STATIC_DIR = BASE_DIR / "static"
_NO_CACHE = {"Cache-Control": "no-cache, must-revalidate"}


def register_frontend(app: FastAPI) -> None:
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    @app.get("/", include_in_schema=False)
    async def root() -> FileResponse:
        return FileResponse(_STATIC_DIR / "index.html", headers=_NO_CACHE)
