package com.breakheal.demo;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.Instant;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;

public class OrderBookEngine {

    public enum Side { BUY, SELL }
    public enum OrderType { LIMIT, MARKET }

    public static class Order {
        private final String orderId;
        private final String traderId;
        private final Side side;
        private final OrderType type;
        private final BigDecimal price;
        private int remainingQuantity;
        private final Instant timestamp;

        public Order(String orderId, String traderId, Side side, OrderType type, BigDecimal price, int quantity) {
            this.orderId = orderId;
            this.traderId = traderId;
            this.side = side;
            this.type = type;
            this.price = price;
            this.remainingQuantity = quantity;
            this.timestamp = Instant.now();
        }

        public String getOrderId() { return orderId; }
        public Side getSide() { return side; }
        public OrderType getType() { return type; }
        public BigDecimal getPrice() { return price; }
        public int getRemainingQuantity() { return remainingQuantity; }
        public void reduceQuantity(int filled) { this.remainingQuantity -= filled; }
        public Instant getTimestamp() { return timestamp; }
    }

    public static class MatchResult {
        public final String takerOrderId;
        public final String makerOrderId;
        public final BigDecimal executionPrice;
        public final int matchedQuantity;
        public final BigDecimal totalValue;

        public MatchResult(String taker, String maker, BigDecimal price, int qty) {
            this.takerOrderId = taker;
            this.makerOrderId = maker;
            this.executionPrice = price;
            this.matchedQuantity = qty;
            // Flaw: Unscaled BigDecimal multiplication can accumulate fractional penny drift
            this.totalValue = price.multiply(BigDecimal.valueOf(qty)).setScale(2, RoundingMode.HALF_UP);
        }

        @Override
        public String toString() {
            return String.format("MATCH: Taker=%s -> Maker=%s | Qty=%d @ $%s (Total: $%s)",
                    takerOrderId, makerOrderId, matchedQuantity, executionPrice, totalValue);
        }
    }

    // Buy orders sorted Descending by price, Ascending by timestamp
    private final PriorityQueue<Order> buyOrders = new PriorityQueue<>((a, b) -> {
        int cmp = b.getPrice().compareTo(a.getPrice());
        return (cmp != 0) ? cmp : a.getTimestamp().compareTo(b.getTimestamp());
    });

    // Sell orders sorted Ascending by price, Ascending by timestamp
    private final PriorityQueue<Order> sellOrders = new PriorityQueue<>((a, b) -> {
        int cmp = a.getPrice().compareTo(b.getPrice());
        return (cmp != 0) ? cmp : a.getTimestamp().compareTo(b.getTimestamp());
    });

    private final Map<String, Order> orderIndex = new ConcurrentHashMap<>();

    /**
     * Places an order and matches it against the opposite order book.
     */
    public synchronized List<MatchResult> placeOrder(Order newOrder) {
        List<MatchResult> executions = new ArrayList<>();

        if (newOrder.getRemainingQuantity() <= 0) {
            throw new IllegalArgumentException("Order quantity must be positive");
        }

        if (newOrder.getSide() == Side.BUY) {
            matchBuyOrder(newOrder, executions);
            if (newOrder.getRemainingQuantity() > 0 && newOrder.getType() == OrderType.LIMIT) {
                buyOrders.add(newOrder);
                orderIndex.put(newOrder.getOrderId(), newOrder);
            }
        } else {
            matchSellOrder(newOrder, executions);
            if (newOrder.getRemainingQuantity() > 0 && newOrder.getType() == OrderType.LIMIT) {
                sellOrders.add(newOrder);
                orderIndex.put(newOrder.getOrderId(), newOrder);
            }
        }

        return executions;
    }

    private void matchBuyOrder(Order buy, List<MatchResult> results) {
        while (!sellOrders.isEmpty() && buy.getRemainingQuantity() > 0) {
            Order bestSell = sellOrders.peek();

            // Bug 3: Strict inequality (>) instead of (>=) ignores exact price matches
            if (buy.getType() == OrderType.LIMIT && buy.getPrice().compareTo(bestSell.getPrice()) < 0) {
                break; // Limit price not met
            }

            int matchQty = Math.min(buy.getRemainingQuantity(), bestSell.getRemainingQuantity());
            buy.reduceQuantity(matchQty);
            bestSell.reduceQuantity(matchQty);

            results.add(new MatchResult(buy.getOrderId(), bestSell.getOrderId(), bestSell.getPrice(), matchQty));

            if (bestSell.getRemainingQuantity() == 0) {
                sellOrders.poll();
                orderIndex.remove(bestSell.getOrderId());
            }
        }
    }

    private void matchSellOrder(Order sell, List<MatchResult> results) {
        while (!buyOrders.isEmpty() && sell.getRemainingQuantity() > 0) {
            Order bestBuy = buyOrders.peek();

            if (sell.getType() == OrderType.LIMIT && sell.getPrice().compareTo(bestBuy.getPrice()) > 0) {
                break;
            }

            int matchQty = Math.min(sell.getRemainingQuantity(), bestBuy.getRemainingQuantity());
            sell.reduceQuantity(matchQty);
            bestBuy.reduceQuantity(matchQty);

            results.add(new MatchResult(sell.getOrderId(), bestBuy.getOrderId(), bestBuy.getPrice(), matchQty));

            if (bestBuy.getRemainingQuantity() == 0) {
                buyOrders.poll();
                orderIndex.remove(bestBuy.getOrderId());
            }
        }
    }

    /**
     * Calculates the Volume Weighted Average Price (VWAP) across all active buy orders.
     */
    public BigDecimal calculateBuyVWAP() {
        // Bug 4: Zero-division crash on empty book
        BigDecimal totalVolumeValue = BigDecimal.ZERO;
        int totalShares = 0;

        for (Order order : buyOrders) {
            BigDecimal orderVal = order.getPrice().multiply(BigDecimal.valueOf(order.getRemainingQuantity()));
            totalVolumeValue = totalVolumeValue.add(orderVal);
            totalShares += order.getRemainingQuantity();
        }

        // ArithmeticException: Division by zero if totalShares == 0
        return totalVolumeValue.divide(BigDecimal.valueOf(totalShares), 4, RoundingMode.HALF_UP);
    }

    // ========================================================
    // TEST RUNNER MAIN METHOD
    // ========================================================
    public static void main(String[] args) {
        System.out.println("=== Testing OrderBookEngine Edge Cases ===");
        OrderBookEngine engine = new OrderBookEngine();

        // 1. Normal matching test
        engine.placeOrder(new Order("S1", "TraderA", Side.SELL, OrderType.LIMIT, new BigDecimal("100.50"), 10));
        List<MatchResult> matches = engine.placeOrder(new Order("B1", "TraderB", Side.BUY, OrderType.LIMIT, new BigDecimal("100.50"), 5));
        
        matches.forEach(System.out::println);
        System.out.println("Remaining buy orders: " + engine.buyOrders.size());

        // 2. Trigger Boundary Bug 4: Zero-Division VWAP on empty book
        System.out.println("\nTesting VWAP on empty buy book (Should throw ArithmeticException):");
        try {
            engine.calculateBuyVWAP();
        } catch (ArithmeticException e) {
            System.out.println("Caught Expected Bug: " + e.getMessage());
        }

        // 3. Trigger Boundary Bug 1: Negative quantity injection
        System.out.println("\nTesting negative quantity injection (-10 shares):");
        engine.placeOrder(new Order("B2", "BadActor", Side.BUY, OrderType.LIMIT, new BigDecimal("99.00"), -10));
        System.out.println("Order book allowed negative quantity, corrupted state.");
    }
}

