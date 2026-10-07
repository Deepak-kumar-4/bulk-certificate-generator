from fastapi import FastAPI

from app.errors import register_error_handlers


def create_app() -> FastAPI:
    app = FastAPI(
        title="Bulk Certificate Generator",
        description="Submit many recipients in one request and get a PDF certificate for each.",
        version="0.1.0",
    )
    register_error_handlers(app)

    @app.get("/health", tags=["health"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
