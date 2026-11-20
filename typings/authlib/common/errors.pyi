class AuthlibBaseError(Exception):
    error: str | None
    description: str
    uri: str | None
    def __init__(
        self, error: str | None = None, description: str | None = None, uri: str | None = None
    ) -> None: ...
