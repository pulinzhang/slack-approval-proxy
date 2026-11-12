"""Typed errors. Handlers write the design envelope. Routers do not raise HTTPException."""


class AppError(Exception):
    """Base error mapped to `{"error", "message"}`."""

    def __init__(self, error: str, message: str, status_code: int) -> None:
        self.error = error
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class UnauthorizedError(AppError):
    def __init__(self) -> None:
        super().__init__("Unauthorized", "Invalid or missing X-API-Key header", 401)


class InvalidSignatureError(AppError):
    def __init__(self) -> None:
        super().__init__(
            "InvalidSignature",
            "Slack signature mismatch or expired timestamp",
            400,
        )


class InvalidPayloadError(AppError):
    def __init__(self, message: str = "Slack payload is missing or not JSON") -> None:
        super().__init__("InvalidPayload", message, 400)


class NotFoundError(AppError):
    def __init__(self, message: str = "Approval request not found") -> None:
        super().__init__("NotFound", message, 404)


class ConflictError(AppError):
    def __init__(self, message: str, request_id: str) -> None:
        self.request_id = request_id
        super().__init__("Conflict", message, 409)


class SlackAPIError(AppError):
    def __init__(self, message: str) -> None:
        super().__init__("SlackAPIError", message, 502)


class MessageTraceError(AppError):
    def __init__(self) -> None:
        super().__init__("MessageTraceError", "Failed to record the exchange", 503)


class ValidationFailure(AppError):
    def __init__(self, message: str) -> None:
        super().__init__("ValidationError", message, 422)


class InternalError(AppError):
    def __init__(self) -> None:
        super().__init__("InternalError", "Internal server error", 500)
