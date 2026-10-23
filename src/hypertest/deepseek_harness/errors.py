"""Public failures contain stable codes, never SDK diagnostics or prompt text."""


class AdapterError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class CapabilityError(AdapterError):
    """The requested capability has not been authorized or implemented."""


class DependencyError(AdapterError):
    """The exact supported SDK/runtime pair is not installed."""


class RecoveryRequired(AdapterError):
    """An operation may have happened; it must not be replayed automatically."""
