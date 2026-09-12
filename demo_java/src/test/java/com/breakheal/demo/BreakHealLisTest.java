package com.breakheal.demo;

import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

public class BreakHealLisTest {
    @Test
    public void testLisConstructor() {
        // Test that the constructor properly initializes the list
        Lis lis = new Lis();
        assertNotNull(lis, "Lis instance should not be null");
        assertNotNull(lis.l, "List field 'l' should be initialized in constructor");
        assertTrue(lis.l.isEmpty(), "List should be empty after construction");
    }
}