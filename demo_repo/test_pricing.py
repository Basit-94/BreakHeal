import pytest
from demo_repo.pricing import calculate_discounted_unit_price


def test_standard_discount():
    result = calculate_discounted_unit_price(price=100.0, discount_percent=20.0, quantity=2)
    assert result == 40.0


def test_invalid_discount_range():
    with pytest.raises(ValueError):
        calculate_discounted_unit_price(price=100.0, discount_percent=-5.0, quantity=1)
    with pytest.raises(ValueError):
        calculate_discounted_unit_price(price=100.0, discount_percent=105.0, quantity=1)
