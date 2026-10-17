class DomainError(Exception):
    """Business-rule violation raised by the service layer; mapped to an HTTP response in main.py."""

    status_code = 400
    code = "domain_error"

    def __init__(self, message: str, code: str | None = None):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code


class NotFound(DomainError):
    status_code = 404
    code = "not_found"


class Forbidden(DomainError):
    status_code = 403
    code = "forbidden"


class Unauthorized(DomainError):
    status_code = 401
    code = "unauthorized"


class Conflict(DomainError):
    status_code = 409
    code = "conflict"


class RateLimited(DomainError):
    status_code = 429
    code = "rate_limited"
