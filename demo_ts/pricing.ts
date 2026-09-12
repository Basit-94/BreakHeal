/**
 * Calculates the unit price after applying a percentage discount (TypeScript).
 * 
 * @param price - Base unit price (must be positive).
 * @param discountPercent - Percentage between 0.0 and 100.0.
 * @param quantity - Quantity of items purchased.
 * @returns The discounted unit price.
 */
export function calculateDiscountedUnitPrice(
    price: number,
    discountPercent: number,
    quantity: number = 1
): number {
    if (discountPercent < 0.0 || discountPercent > 100.0) {
        throw new RangeError("discountPercent must be between 0.0 and 100.0");
    }

    const discountFactor = 1.0 - (discountPercent / 100.0);
    return (price * discountFactor) / quantity; // BUG: Returns Infinity when quantity is 0
}
