"""Application error type mapped to HTTP responses with stable error codes."""

from __future__ import annotations


class AppError(Exception):
    status_code = 400
    code = "error"

    def __init__(
        self,
        code: str | None = None,
        message: str | None = None,
        status_code: int | None = None,
        **details,
    ):
        self.code = code or self.code
        self.message = message or self.code
        self.status_code = status_code or self.status_code
        self.details = details
        super().__init__(self.message)


class NotFound(AppError):
    status_code = 404
    code = "not_found"


class Forbidden(AppError):
    status_code = 403
    code = "forbidden"


class Unauthorized(AppError):
    status_code = 401
    code = "unauthorized"


class Conflict(AppError):
    status_code = 409
    code = "conflict"


class ValidationFailed(AppError):
    status_code = 422
    code = "validation_failed"
