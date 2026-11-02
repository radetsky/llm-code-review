"""Order processing."""

from service import notify, pricing, validation


def process_order(order: dict) -> dict:
    items = order["items"]
    validation.validate_items(items)

    is_member = bool(order.get("customer", {}).get("is_member"))
    value = pricing.subtotal(items, is_member)
    shipping = pricing.shipping_for(value)
    total = pricing.total_for(value, shipping)

    print(notify.order_message(order["id"], total))
    return {"id": order["id"], "total": total, "shipping": shipping}
