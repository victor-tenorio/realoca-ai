"""Public error formatting; never return database messages or tracebacks."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError, ResponseValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException


class APIError(Exception):
    def __init__(self, status_code: int, code: str, message: str, details: dict):
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


def error_response(
    status: int,
    code: str,
    message: str,
    details: dict | None = None,
    headers: dict | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        headers=headers,
        content={
            "error": {"code": code, "message": message, "details": details or {}},
        },
    )


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(APIError)
    async def api_error(request: Request, exc: APIError):
        return error_response(exc.status_code, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError):
        # The API contract expects explicit 400 validation errors for malformed payloads.
        return error_response(400, "INVALID_REQUEST", "Parâmetros inválidos")

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        return error_response(
            exc.status_code,
            f"HTTP_{exc.status_code}",
            str(exc.detail),
            headers=exc.headers,
        )

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request: Request, exc: SQLAlchemyError):
        return error_response(503, "DATABASE_UNAVAILABLE", "Consulta indisponível")

    @app.exception_handler(ResponseValidationError)
    async def invalid_response(request: Request, exc: ResponseValidationError):
        return error_response(500, "INTERNAL_ERROR", "Falha ao preparar resposta")

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception):
        return error_response(500, "INTERNAL_ERROR", "Falha interna")
