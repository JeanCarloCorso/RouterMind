from typing import Any

from fastapi.responses import JSONResponse


class RouteMindError(Exception):
    def __init__(self, status_code: int, message: str, code: str, metadata: dict[str, Any] | None = None):
        self.status_code = status_code
        self.message = message
        self.code = code
        self.metadata = metadata or {}
        super().__init__(message)


def error_response(exc: RouteMindError) -> JSONResponse:
    error: dict[str, Any] = {"message": exc.message, "code": exc.code}
    if exc.metadata:
        error["metadata"] = exc.metadata
    return JSONResponse(status_code=exc.status_code, content={"error": error})
