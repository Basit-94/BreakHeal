export interface RateLimitConfig {
  capacity: number;          // Maximum burst tokens allowed
  refillRatePerSecond: number; // Tokens added back per second
  windowSizeMs: number;       // Window size for decay calculations
}

export interface ClientBucket {
  tokens: number;
  lastRefillTimestamp: number;
  totalRequestsServed: number;
}

export interface RateLimitResult {
  allowed: boolean;
  remainingTokens: number;
  retryAfterMs: number;
  totalServed: number;
}

export class DistributedRateLimiter {
  private tiers: Map<string, RateLimitConfig>;
  private buckets: Map<string, ClientBucket>;

  constructor() {
    this.tiers = new Map([
      ["standard", { capacity: 60, refillRatePerSecond: 1, windowSizeMs: 60000 }],
      ["premium", { capacity: 300, refillRatePerSecond: 5, windowSizeMs: 60000 }],
      ["internal", { capacity: 10000, refillRatePerSecond: 500, windowSizeMs: 1000 }],
    ]);
    this.buckets = new Map();
  }

  /**
   * Evaluates if a request should be admitted and consumes tokens.
   */
  public consume(
    clientId: string,
    tier: string = "standard",
    tokensRequested: number = 1,
    now: number = Date.now()
  ): RateLimitResult {
    // Bug 1: Missing tier fallback; crashes with TypeError if tier doesn't exist
    const config = this.tiers.get(tier) ?? this.tiers.get("standard")!;

    let bucket = this.buckets.get(clientId);

    if (!bucket) {
      bucket = {
        tokens: config.capacity,
        lastRefillTimestamp: now,
        totalRequestsServed: 0,
      };
      this.buckets.set(clientId, bucket);
    }

    // Bug 2: Clock skew vulnerability (now < lastRefillTimestamp drains tokens to negative)
    const elapsedSeconds = (now - bucket.lastRefillTimestamp) / 1000;
    const tokensToAdd = elapsedSeconds * config.refillRatePerSecond;

    // Refill bucket up to max burst capacity
    bucket.tokens = Math.min(config.capacity, bucket.tokens + tokensToAdd);
    bucket.lastRefillTimestamp = now;

    // Bug 3: Negative token exploit (tokensRequested <= 0 adds tokens back to bucket)
    // Bug 4: Strict inequality (> instead of >=) rejects valid 0-cost inquiries
    if (tokensRequested < 0) {
      return {
        allowed: false,
        remainingTokens: Math.floor(bucket.tokens),
        retryAfterMs: 0,
        totalServed: bucket.totalRequestsServed,
      };
    }

    if (bucket.tokens < tokensRequested) {
      // Bug 5: Zero-division crash if refillRatePerSecond is 0
      const missingTokens = tokensRequested - bucket.tokens;
      const retryAfterMs = Math.ceil((missingTokens / config.refillRatePerSecond) * 1000);

      return {
        allowed: false,
        remainingTokens: Math.floor(bucket.tokens),
        retryAfterMs,
        totalServed: bucket.totalRequestsServed,
      };
    }

    bucket.tokens -= tokensRequested;
    bucket.totalRequestsServed += 1;

    return {
      allowed: true,
      remainingTokens: Math.floor(bucket.tokens),
      retryAfterMs: 0,
      totalServed: bucket.totalRequestsServed,
    };
  }
}