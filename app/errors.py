"""Typed application errors that keep the domain free of web-framework imports.

The service and client layers raise these; the FastAPI layer maps them onto
HTTP responses in a single exception handler, so business rules never import
``fastapi`` themselves.
"""


class AppError(Exception):
    """Error carrying an HTTP status code and a client-safe detail message.

    Args:
        detail: human-readable message returned to the API client.
        status_code: HTTP status to answer with; defaults to the class default.

    Usage example::

        raise DomainError("Нельзя убрать последний оффер", 400)
    """

    status_code = 500

    def __init__(self, detail: str, status_code: int | None = None) -> None:
        super().__init__(detail)
        self.detail = detail
        if status_code is not None:
            self.status_code = status_code


class UpstreamError(AppError):
    """Keitaro rejected the request or could not be reached."""

    status_code = 502


class DomainError(AppError):
    """A business rule rejected the operation."""

    status_code = 400
