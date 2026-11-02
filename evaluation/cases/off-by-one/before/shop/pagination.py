def paginate(items: list, page: int, size: int) -> list:
    """Return the items of a page. The first page is 0."""
    start = page * size
    return items[start : start + size]
