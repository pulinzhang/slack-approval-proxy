"""Scan `app.routers` in name order and mount each `router`."""

import importlib
import pkgutil

from fastapi import APIRouter, FastAPI

from app.utils.logging_config import get_logger

logger = get_logger("bootstrap.routers")


def include_scanned_routers(app: FastAPI) -> None:
    package = importlib.import_module("app.routers")
    prefix = f"{package.__name__}."
    count = 0
    for _finder, name, is_package in pkgutil.iter_modules(package.__path__, prefix):
        if is_package:
            continue
        module = importlib.import_module(name)
        router = getattr(module, "router", None)
        if not isinstance(router, APIRouter):
            logger.warning("scanned module has no router name=%s", name)
            continue
        app.include_router(router)
        logger.info("scanned router name=%s prefix=%s", name, router.prefix)
        count += 1
    logger.info("registered routers count=%s", count)
