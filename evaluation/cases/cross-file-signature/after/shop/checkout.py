from shop.cart import cart_total
from shop.prices import parse_price


def shipping_cost(label: str) -> float:
    return parse_price(label, "EUR")


def order_total(items: list[dict], shipping_label: str) -> float:
    return cart_total(items) + shipping_cost(shipping_label)
