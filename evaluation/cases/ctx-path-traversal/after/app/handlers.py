from app.storage import MAX_SIZE, UPLOAD_DIR, build_path, ensure_dir


def save_upload(filename: str, data: bytes) -> str:
    if len(data) > MAX_SIZE:
        raise ValueError("file is too large")
    path = build_path(UPLOAD_DIR, filename)
    ensure_dir(path)
    with open(path, "wb") as handle:
        handle.write(data)
    return path
