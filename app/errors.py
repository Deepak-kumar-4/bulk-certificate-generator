from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class AppError(Exception):
    """Domain error that is rendered as {"error": {"code", "message"}}."""

    status_code = 400
    code = "BAD_REQUEST"

    def __init__(self, message: str, *, code: str | None = None, status_code: int | None = None):
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        if status_code is not None:
            self.status_code = status_code


class NotFoundError(AppError):
    status_code = 404
    code = "NOT_FOUND"


class ConflictError(AppError):
    status_code = 409
    code = "CONFLICT"


def error_body(code: str, message: str, details: list | None = None) -> dict:
    error: dict = {"code": code, "message": message}
    if details:
        error["details"] = details
    return {"error": error}


def _format_validation_error(err: dict) -> dict:
    loc = [str(part) for part in err.get("loc", ()) if part != "body"]
    message = err.get("msg", "invalid value").removeprefix("Value error, ")
    return {"field": ".".join(loc), "message": message}


async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content=error_body(exc.code, exc.message))


async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    details = [_format_validation_error(err) for err in exc.errors()]
    message = "; ".join(
        f"{d['field']}: {d['message']}" if d["field"] else d["message"] for d in details
    )
    return JSONResponse(
        status_code=422,
        content=error_body("VALIDATION_ERROR", message or "Invalid request", details),
    )


async def http_error_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = {400: "BAD_REQUEST", 404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}.get(
        exc.status_code, "HTTP_ERROR"
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=error_body(code, str(exc.detail)),
        headers=getattr(exc, "headers", None),
    )


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_error_handler)
