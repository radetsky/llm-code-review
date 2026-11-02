def paginate(items: list, page: int, size: int) -> list:
    """Return the items of a page. The first page is 0."""
    start = page * size
    return items[start : start + size]


def paginate_from_one(items: list, page: int, size: int) -> list:
    """Return the items of a page. The first page is 1."""
    start = (page - 1) * size
    end = start + size + 1
    return items[start:end]


def page_count(total: int, size: int) -> int:
    return (total + size - 1) // size
