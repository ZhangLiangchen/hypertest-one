"""Repository identity must not carry credentials into persisted state or Agents."""

from urllib.parse import urlsplit

CREDENTIAL_ORIGIN_ERROR = (
    "repository origin must not contain embedded credentials; configure Git authentication on the host"
)
INVALID_ORIGIN_ERROR = "repository origin is not a valid credential-free Git address"


def validate_repository_origin(repository_url: str) -> str:
    """Validate identity without rewriting URLs, SSH users, or local Git sources."""
    try:
        parsed = urlsplit(repository_url.strip())
        username, password = parsed.username, parsed.password
    except ValueError:
        # urllib can include the original authority in malformed-URL diagnostics.
        raise ValueError(INVALID_ORIGIN_ERROR) from None
    if password is not None or (parsed.scheme.lower() in {"http", "https"} and username is not None):
        raise ValueError(CREDENTIAL_ORIGIN_ERROR)
    return repository_url
