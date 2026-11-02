import re

_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]{0,40}$")


def ensure_identifier(value: str) -> str:
    """Return the value if it is a plain SQL identifier. Raise ValueError if not."""
    if not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"invalid identifier: {value!r}")
    return value
