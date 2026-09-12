package com.breakheal.demo;

import java.time.Duration;
import java.time.Instant;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.locks.ReentrantLock;

public class ResilientJobScheduler {

    public enum JobStatus { PENDING, RUNNING, COMPLETED, FAILED, RETRYING, DEAD_LETTER }
    public enum CircuitState { CLOSED, OPEN, HALF_OPEN }

    // ========================================================
    // 1. DOMAIN MODELS
    // ========================================================

    public record JobDefinition(
        String jobId,
        String group,
        Runnable task,
        int maxRetries,
        Duration initialBackoff,
        double backoffMultiplier
    ) {}

    public static class JobExecutionRecord {
        public final String jobId;
        public final String group;
        public int attemptCount;
        public JobStatus status;
        public Instant lastAttemptTimestamp;
        public String lastFailureReason;

        public JobExecutionRecord(String jobId, String group) {
            this.jobId = jobId;
            this.group = group;
            this.attemptCount = 0;
            this.status = JobStatus.PENDING;
            this.lastAttemptTimestamp = Instant.now();
        }
    }

    // ========================================================
    // 2. CIRCUIT BREAKER
    // ========================================================

    public static class CircuitBreaker {
        private final String group;
        private final int failureThreshold;
        private final Duration resetTimeout;

        private CircuitState state = CircuitState.CLOSED;
        private final AtomicInteger failureCounter = new AtomicInteger(0);
        private final AtomicInteger successCounter = new AtomicInteger(0);
        private Instant lastStateChanged = Instant.now();
        private final ReentrantLock lock = new ReentrantLock();

        public CircuitBreaker(String group, int failureThreshold, Duration resetTimeout) {
            this.group = group;
            this.failureThreshold = failureThreshold;
            this.resetTimeout = resetTimeout;
        }

        public boolean allowExecution() {
            lock.lock();
            try {
                if (state == CircuitState.OPEN) {
                    // Check if cool-off period has passed to test the waters
                    if (Duration.between(lastStateChanged, Instant.now()).compareTo(resetTimeout) >= 0) {
                        state = CircuitState.HALF_OPEN;
                        lastStateChanged = Instant.now();
                        return true;
                    }
                    return false;
                }
                return true;
            } finally {
                lock.unlock();
            }
        }

        public void recordSuccess() {
            lock.lock();
            try {
                failureCounter.set(0);
                if (state == CircuitState.HALF_OPEN) {
                    state = CircuitState.CLOSED;
                    lastStateChanged = Instant.now();
                }
            } finally {
                lock.unlock();
            }
        }

        public void recordFailure() {
            lock.lock();
            try {
                int failures = failureCounter.incrementAndGet();
                if (state == CircuitState.HALF_OPEN || failures >= failureThreshold) {
                    state = CircuitState.OPEN;
                    lastStateChanged = Instant.now();
                }
            } finally {
                lock.unlock();
            }
        }

        public CircuitState getState() { return state; }
    }

    // ========================================================
    // 3. CORE SCHEDULER ENGINE
    // ========================================================

    private final ScheduledExecutorService workerPool;
    private final Map<String, CircuitBreaker> circuitBreakers = new ConcurrentHashMap<>();
    private final Map<String, JobExecutionRecord> auditLog = new ConcurrentHashMap<>();
    private final Queue<JobExecutionRecord> deadLetterQueue = new ConcurrentLinkedQueue<>();

    public ResilientJobScheduler(int poolSize) {
        this.workerPool = Executors.newScheduledThreadPool(poolSize);
    }

    public void submit(JobDefinition job) {
        auditLog.putIfAbsent(job.jobId(), new JobExecutionRecord(job.jobId(), job.group()));
        dispatch(job, Duration.ZERO);
    }

    private void dispatch(JobDefinition job, Duration delay) {
        workerPool.schedule(() -> executeJob(job), delay.toMillis(), TimeUnit.MILLISECONDS);
    }

    private void executeJob(JobDefinition job) {
        JobExecutionRecord record = auditLog.get(job.jobId());
        CircuitBreaker breaker = circuitBreakers.computeIfAbsent(
            job.group(), g -> new CircuitBreaker(g, 3, Duration.ofSeconds(5))
        );

        if (!breaker.allowExecution()) {
            record.status = JobStatus.FAILED;
            record.lastFailureReason = "Circuit breaker is OPEN for group: " + job.group();
            return;
        }

        record.attemptCount++;
        record.lastAttemptTimestamp = Instant.now();
        record.status = JobStatus.RUNNING;

        try {
            // Execute actual task payload
            job.task().run();

            // Succeeded
            record.status = JobStatus.COMPLETED;
            breaker.recordSuccess();
        } catch (Throwable t) {
            breaker.recordFailure();
            record.lastFailureReason = t.getMessage();

            if (record.attemptCount <= job.maxRetries()) {
                record.status = JobStatus.RETRYING;
                long backoffMs = calculateBackoffMillis(job, record.attemptCount);
                dispatch(job, Duration.ofMillis(backoffMs));
            } else {
                record.status = JobStatus.DEAD_LETTER;
                deadLetterQueue.add(record);
            }
        }
    }

    /**
     * Computes exponential backoff delay with jitter.
     */
    public long calculateBackoffMillis(JobDefinition job, int attempt) {
        // Bug 1: Integer overflow flaw on high attempt counts with exponential power
        // Math.pow with high multipliers easily overflows long max if not clamped
        double rawBackoff = job.initialBackoff().toMillis() * Math.pow(job.backoffMultiplier(), attempt - 1);

        // Bug 2: Zero or negative initial backoff produces negative delays or thread hangs
        long backoff = (long) rawBackoff;

        // Add 10% deterministic pseudo-jitter
        long jitter = (long) (backoff * 0.1);
        return backoff + jitter;
    }

    /**
     * Computes health ratio of completed vs dead-lettered jobs.
     */
    public double calculateSystemFailureRate() {
        long totalJobs = auditLog.size();
        long deadLetterJobs = deadLetterQueue.size();

        if (totalJobs == 0) {
            return 0.0;
        }

        return (double) deadLetterJobs / totalJobs;
    }

    public void shutdown() {
        workerPool.shutdown();
    }

    // ========================================================
    // TEST RUNNER
    // ========================================================

    public static void main(String[] args) throws InterruptedException {
        System.out.println("=== Starting ResilientJobScheduler ===");
        ResilientJobScheduler scheduler = new ResilientJobScheduler(4);

        // 1. Boundary Bug: Division by zero test on empty system health
        System.out.println("Initial Failure Rate (expecting NaN bug): " + scheduler.calculateSystemFailureRate());

        // 2. Failing Job that trips the Circuit Breaker
        AtomicInteger attempts = new AtomicInteger(0);
        JobDefinition fragileJob = new JobDefinition(
            "JOB_EXT_PAYMENT",
            "payment-gateway",
            () -> {
                attempts.incrementAndGet();
                throw new RuntimeException("503 Service Unavailable");
            },
            4,
            Duration.ofMillis(200),
            2.0
        );

        scheduler.submit(fragileJob);

        // Allow execution and retries to complete
        Thread.sleep(3000);

        JobExecutionRecord finalRecord = scheduler.auditLog.get("JOB_EXT_PAYMENT");
        System.out.println("Final Job Status: " + finalRecord.status);
        System.out.println("Total Execution Attempts: " + finalRecord.attemptCount);
        System.out.println("Circuit State: " + scheduler.circuitBreakers.get("payment-gateway").getState());
        System.out.println("DLQ Size: " + scheduler.deadLetterQueue.size());

        scheduler.shutdown();
    }
}