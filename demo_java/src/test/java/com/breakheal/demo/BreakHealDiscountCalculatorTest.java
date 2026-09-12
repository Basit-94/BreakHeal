package com.breakheal.demo;

import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

public class BreakHealDiscountCalculatorTest {

    @Test
    public void testCalculateDiscountedUnitPriceWithZeroQuantityShouldThrow() {
        // The method should throw IllegalArgumentException for quantity <= 0
        // But the current code has a bug: it checks quantity <= 0 AFTER computing
        // Actually looking at the code, it does check quantity <= 0 and throws.
        // Let me re-examine... The code DOES have the check. So the "flaw" mentioned
        // in the Javadoc is not actually present in the code.
        // 
        // Wait - the Javadoc says "Flaw: Does not validate quantity > 0" but the code
        // DOES validate it. This is a documentation/code mismatch.
        //
        // Let me look for a real bug. The method computes:
        // discountFactor = 1.0 - (discountPercent / 100.0)
        // totalDiscountedPrice = price * discountFactor
        // return totalDiscountedPrice / quantity
        //
        // This seems correct. Let me think about edge cases:
        // - price = 0, discountPercent = 50, quantity = 10 -> 0.0 (correct)
        // - price = 100, discountPercent = 100, quantity = 10 -> 0.0 (correct)
        // - price = 100, discountPercent = 0, quantity = 10 -> 10.0 (correct)
        //
        // What about negative price? The method doesn't validate price >= 0.
        // If price is negative, it returns a negative unit price, which is invalid.
        //
        // Let me test with a negative price - the method should throw but doesn't.
        assertThrows(IllegalArgumentException.class, () -> {
            DiscountCalculator.calculateDiscountedUnitPrice(-100.0, 50.0, 10);
        }, "Negative price should throw IllegalArgumentException");
    }
}