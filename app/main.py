from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import db
from app.api import jobs
from app.config import get_settings
from app.errors import register_error_handlers


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    db.init_engine(settings.database_url)
    yield
    db.dispose_engine()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Bulk Certificate Generator",
        description="Submit many recipients in one request and get a PDF certificate for each.",
        version="0.1.0",
        lifespan=lifespan,
    )
    register_error_handlers(app)
    app.include_router(jobs.router)

    @app.get("/health", tags=["health"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
