class ClientError(RuntimeError):
    """A stable, non-sensitive error code safe for MCP delivery."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)
