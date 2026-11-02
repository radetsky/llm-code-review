"""File storage helpers."""

import os

UPLOAD_DIR = "/srv/uploads"
MAX_SIZE = 5 * 1024 * 1024


def build_path(base: str, name: str) -> str:
    """Return the path of a stored file."""
    return os.path.join(base, name)


def ensure_dir(path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
