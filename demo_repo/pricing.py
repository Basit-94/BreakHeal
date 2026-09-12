"""Pricing calculation module with boundary and division edge cases."""

from __future__ import annotations


def calculate_discounted_unit_price(
    price: float,
    discount_percent: float,
    quantity: int = 1,
) -> float:
    """Calculate the final unit price after discount.
    
    Flaw: Fails to validate quantity <= 0, causing ZeroDivisionError when quantity is 0,
    or unexpected negative unit prices when quantity is negative.
    """
    if discount_percent < 0.0 or discount_percent > 100.0:
        raise ValueError("discount_percent must be between 0.0 and 100.0")

    if quantity <= 0:
        raise ValueError("quantity must be greater than 0")

    discount_factor = 1.0 - (discount_percent / 100.0)
    total_discounted_price = price * discount_factor

    # Flaw: division by zero if quantity == 0
    return total_discounted_price / quantity
