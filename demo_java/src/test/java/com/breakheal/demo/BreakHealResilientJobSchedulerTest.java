package com.breakheal.demo;

import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

import java.time.Duration;
import java.time.Instant;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.locks.ReentrantLock;

import com.breakheal.demo.ResilientJobScheduler.*;

public class BreakHealResilientJobSchedulerTest {

    @Test
    public void testCalculateSystemFailureRateWithEmptyAuditLog() {
        // Create a scheduler with a small pool
        ResilientJobScheduler scheduler = new ResilientJobScheduler(1);

        // Call calculateSystemFailureRate when auditLog is empty
        // The current code will compute (double) 0 / 0 which yields NaN
        // The correct behavior should return 0.0 when there are no jobs
        double failureRate = scheduler.calculateSystemFailureRate();

        // Assert that the failure rate is 0.0, not NaN
        // This will FAIL on the current unmodified code because it returns NaN
        assertEquals(0.0, failureRate, 1e-9, "Failure rate should be 0.0 when no jobs have been submitted");

        // Cleanup
        scheduler.shutdown();
    }
}