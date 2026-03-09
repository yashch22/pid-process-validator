"""FastAPI application entrypoint."""
import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI

# Ensure app loggers (vector_store, graph, etc.) output to stdout
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
    force=True,
)
from fastapi.middleware.cors import CORSMiddleware

from app.api import api_router
from app.core.config import get_settings
from app.db import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield
    # shutdown if needed


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        description="P&ID to graph conversion and SOP validation API",
        version="1.0.0",
        lifespan=lifespan,
        response_model_by_alias=True,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_router)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app


app = create_app()
