import pytest

from service.orders import process_order


def make_order(price, quantity=1, member=False):
    return {
        "id": "o-1",
        "items": [{"price": price, "quantity": quantity}],
        "customer": {"is_member": member},
    }


def test_empty_order_is_rejected():
    with pytest.raises(ValueError):
        process_order({"id": "o-2", "items": []})


def test_negative_price_is_rejected():
    with pytest.raises(ValueError):
        process_order(make_order(-1))


def test_zero_quantity_is_rejected():
    with pytest.raises(ValueError):
        process_order(make_order(10, quantity=0))


def test_member_gets_a_discount():
    plain = process_order(make_order(100))["total"]
    member = process_order(make_order(100, member=True))["total"]
    assert member < plain


def test_result_has_the_order_id():
    assert process_order(make_order(60))["id"] == "o-1"
