"""Order processing."""

DISCOUNT_RATE = 0.1
FREE_SHIPPING_FROM = 50.0
SHIPPING_COST = 4.99


def process_order(order: dict) -> dict:
    items = order["items"]
    if not items:
        raise ValueError("empty order")
    for item in items:
        if item["quantity"] <= 0:
            raise ValueError("bad quantity")
        if item["price"] < 0:
            raise ValueError("bad price")

    subtotal = sum(i["price"] * i["quantity"] for i in items)
    if order.get("customer", {}).get("is_member"):
        subtotal = subtotal * (1 - DISCOUNT_RATE)
    shipping = 0.0 if subtotal >= FREE_SHIPPING_FROM else SHIPPING_COST
    total = round(subtotal + shipping, 2)

    message = f"Order {order['id']} total: {total}"
    print(message)
    return {"id": order["id"], "total": total, "shipping": shipping}
