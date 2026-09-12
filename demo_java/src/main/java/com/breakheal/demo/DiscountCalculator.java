package com.breakheal.demo;

/**
 * Pricing calculation utility with boundary conditions.
 */
public class DiscountCalculator {

    /**
     * Calculate unit price after discount divided across quantity.
     *
     * Flaw: Does not validate quantity > 0; when quantity is 0 or negative,
     * produces Double.POSITIVE_INFINITY or invalid negative prices instead
     * of throwing IllegalArgumentException.
     */
    public static double calculateDiscountedUnitPrice(double price, double discountPercent, int quantity) {
        if (price < 0.0) {
            throw new IllegalArgumentException("price must be non-negative");
        }

        if (discountPercent < 0.0 || discountPercent > 100.0) {
            throw new IllegalArgumentException("discountPercent must be between 0.0 and 100.0");
        }

        if (quantity <= 0) {
            throw new IllegalArgumentException("quantity must be greater than 0");
        }

        double discountFactor = 1.0 - (discountPercent / 100.0);
        double totalDiscountedPrice = price * discountFactor;

        return totalDiscountedPrice / quantity;
    }
}
