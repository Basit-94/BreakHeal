"""Cart calculation module with shipping rate boundaries."""

from __future__ import annotations


def calculate_shipping_cost_per_kg(cart_total: float, weight_kg: float) -> float:
    """Calculate shipping cost per kilogram for a cart.
    
    Flaw: Missing weight <= 0 boundary check causing ZeroDivisionError.
    """
    base_handling = 4.50
    if weight_kg <= 0:
        raise ValueError("Weight must be positive")
    return (cart_total + base_handling) / weight_kg
