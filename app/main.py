import logging
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import db
from app.api import certificates, jobs
from app.config import get_settings
from app.errors import register_error_handlers
from app.services import processor

logger = logging.getLogger(__name__)


def resume_unfinished_jobs(app: FastAPI) -> None:
    """Restart recovery: pick up jobs that were cut off by a restart.

    Safe because process_job only touches certificates that are still PENDING, so anything
    generated before the restart is never regenerated. Runs on a background thread so the
    server starts accepting requests straight away.
    """
    app.state.recovery_thread = None
    job_ids = processor.unfinished_job_ids()
    if not job_ids:
        return
    logger.info("Resuming %d unfinished job(s): %s", len(job_ids), ", ".join(job_ids))
    thread = threading.Thread(
        target=processor.process_jobs, args=(job_ids,), name="job-recovery", daemon=True
    )
    thread.start()
    app.state.recovery_thread = thread


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    db.init_engine(settings.database_url)
    resume_unfinished_jobs(app)
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
    app.include_router(certificates.router)

    @app.get("/health", tags=["health"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
