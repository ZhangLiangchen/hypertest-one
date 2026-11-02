"""Bounded, non-secret Cloud failure projections."""

REPORT_CONTENT_REJECTED = "REPORT_CONTENT_REJECTED"


class CloudBlocked(RuntimeError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)
