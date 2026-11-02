"""Prices, discounts and shipping."""

DISCOUNT_RATE = 0.1
FREE_SHIPPING_FROM = 50.0
SHIPPING_COST = 4.99


def subtotal(items: list, is_member: bool) -> float:
    value = sum(i["price"] * i["quantity"] for i in items)
    if is_member:
        value = value * (1 - DISCOUNT_RATE)
    return value


def shipping_for(value: float) -> float:
    return 0.0 if value < FREE_SHIPPING_FROM else SHIPPING_COST


def total_for(value: float, shipping: float) -> float:
    return round(value + shipping, 2)
