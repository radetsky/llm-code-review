import requests

from app import settings


def charge(customer_id: str, cents: int) -> dict:
    response = requests.post(
        f"{settings.PAYMENT_API_URL}/charges",
        headers={"Authorization": f"Bearer {settings.PAYMENT_API_KEY}"},
        json={"customer": customer_id, "amount": cents},
        timeout=settings.REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    return response.json()
