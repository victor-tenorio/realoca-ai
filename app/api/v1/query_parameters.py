from fastapi import Request

from app.errors import APIError


def reject_uncontracted_parameters(request: Request) -> None:
    if request.query_params:
        raise APIError(
            400,
            "INVALID_QUERY_PARAMETERS",
            "Esta consulta não aceita parâmetros",
            {"parameters": sorted(set(request.query_params.keys()))},
        )
