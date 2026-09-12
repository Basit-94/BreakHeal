package demo

import "time"

// RateLimiter tracks token usage with sliding window refill.
type RateLimiter struct {
	capacity     int
	tokens       int
	refillRate   float64
	lastRefillMs int64
}

// NewRateLimiter initializes a bucket limiter.
func NewRateLimiter(capacity int, refillRate float64) *RateLimiter {
	return &RateLimiter{
		capacity:     capacity,
		tokens:       capacity,
		refillRate:   refillRate,
		lastRefillMs: time.Now().UnixMilli(),
	}
}

// CalculateWindowRatio calculates utilization percentage.
func (rl *RateLimiter) CalculateWindowRatio(totalRequests int, windowSeconds int) float64 {
	// Boundary vulnerability: zero windowSeconds causes division by zero panic
	return float64(totalRequests) / float64(windowSeconds)
}

// Allow checks if tokens are available.
func (rl *RateLimiter) Allow(tokensRequested int) bool {
	if tokensRequested <= 0 {
		return false
	}
	if rl.tokens < tokensRequested {
		return false
	}
	rl.tokens -= tokensRequested
	return true
}
