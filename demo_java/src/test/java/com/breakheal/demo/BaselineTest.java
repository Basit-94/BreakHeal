package com.breakheal.demo;

import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

public class BaselineTest {

    @Test
    public void testStandardDiscount() {
        double result = DiscountCalculator.calculateDiscountedUnitPrice(100.0, 20.0, 2);
        assertEquals(40.0, result, 0.001);
    }

    @Test
    public void testInvalidDiscountPercent() {
        assertThrows(IllegalArgumentException.class, () -> {
            DiscountCalculator.calculateDiscountedUnitPrice(100.0, -10.0, 1);
        });
        assertThrows(IllegalArgumentException.class, () -> {
            DiscountCalculator.calculateDiscountedUnitPrice(100.0, 110.0, 1);
        });
    }
}
