from typing import Any

from pydantic import BaseModel, ConfigDict


class ErrorDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str
    message: str
    details: dict[str, Any]


class ErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    error: ErrorDetail


QUERY_ERROR_RESPONSES = {
    400: {
        "model": ErrorResponse,
        "description": "Parâmetro não contratado ou inválido",
    },
    422: {"model": ErrorResponse, "description": "Dados de origem impedem publicação"},
    500: {"model": ErrorResponse, "description": "Erro interno"},
    503: {"model": ErrorResponse, "description": "Banco indisponível"},
}
