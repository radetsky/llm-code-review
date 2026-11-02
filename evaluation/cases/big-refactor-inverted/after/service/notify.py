"""Messages about orders."""


def order_message(order_id: str, total: float) -> str:
    return f"Order {order_id} total: {total}"
