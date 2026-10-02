from __future__ import annotations


class RadarError(Exception):
    """Base class for structured, user-facing errors."""

    code = "radar_error"
    status = 500

    def __init__(self, message: str, *, details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict:
        return {"error": self.code, "message": self.message, "details": self.details}


class NotConfigured(RadarError):
    code = "not_configured"
    status = 503


class NotFound(RadarError):
    code = "not_found"
    status = 404


class ValidationFailed(RadarError):
    code = "validation_failed"
    status = 422


class SourceError(RadarError):
    code = "source_error"
    status = 502


class BudgetExceeded(RadarError):
    code = "budget_exceeded"
    status = 429
