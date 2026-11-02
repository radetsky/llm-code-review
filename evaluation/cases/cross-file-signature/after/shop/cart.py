from shop.prices import parse_price


def cart_total(items: list[dict]) -> float:
    total = 0.0
    for item in items:
        total += parse_price(item["price"], "EUR") * item["quantity"]
    return total
