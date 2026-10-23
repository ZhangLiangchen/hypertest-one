"""Bounded, non-secret Cloud failure projections."""


class CloudBlocked(RuntimeError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)
