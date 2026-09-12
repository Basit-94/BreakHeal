package com.breakheal.demo;

import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

import java.math.BigDecimal;
import java.util.List;

import com.breakheal.demo.OrderBookEngine.*;

public class BreakHealOrderBookEngineTest {

    @Test
    void testPlaceOrderWithZeroQuantityShouldNotCorruptState() {
        OrderBookEngine engine = new OrderBookEngine();

        // Place a valid sell order first
        Order sellOrder = new Order("S1", "TraderA", Side.SELL, OrderType.LIMIT, new BigDecimal("100.00"), 10);
        engine.placeOrder(sellOrder);

        // Place a buy order with zero quantity - this should be rejected or handled gracefully
        // Current code does not validate quantity, so it will proceed with remainingQuantity = 0
        // The matchBuyOrder loop won't execute (buy.getRemainingQuantity() > 0 is false)
        // But the order won't be added to buyOrders either (remainingQuantity > 0 is false)
        // However, the real issue is that negative quantities corrupt state
        
        // Let's test with negative quantity which is more clearly a bug
        Order badBuyOrder = new Order("B_BAD", "BadActor", Side.BUY, OrderType.LIMIT, new BigDecimal("105.00"), -5);
        
        // The current code allows this order through without validation
        // After placeOrder, the order's remainingQuantity is -5
        // It won't be added to buyOrders (since -5 > 0 is false)
        // But we can verify that the engine should reject such orders
        
        // The bug: no validation means negative quantity orders are silently accepted
        // We assert that the engine should throw an exception for invalid quantity
        assertThrows(IllegalArgumentException.class, () -> {
            engine.placeOrder(badBuyOrder);
        }, "placeOrder should reject orders with negative quantity");
    }
}