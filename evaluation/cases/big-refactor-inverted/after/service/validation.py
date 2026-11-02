"""Checks for the items of an order."""


def validate_items(items: list) -> None:
    if not items:
        raise ValueError("empty order")
    for item in items:
        validate_item(item)


def validate_item(item: dict) -> None:
    if item["quantity"] <= 0:
        raise ValueError("bad quantity")
    if item["price"] < 0:
        raise ValueError("bad price")
