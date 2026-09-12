/**
 * Calculates the unit price after applying a percentage discount.
 * 
 * @param {number} price - Base unit price (must be positive).
 * @param {number} discountPercent - Percentage between 0.0 and 100.0.
 * @param {number} quantity - Quantity of items purchased.
 * @returns {number} The discounted unit price.
 */
export function calculateDiscountedUnitPrice(price, discountPercent, quantity = 1) {
    if (discountPercent < 0.0 || discountPercent > 100.0) {
        throw new RangeError("discountPercent must be between 0.0 and 100.0");
    }

    const discountFactor = 1.0 - (discountPercent / 100.0);
    return (price * discountFactor) / quantity; // BUG: Returns Infinity when quantity is 0
}
