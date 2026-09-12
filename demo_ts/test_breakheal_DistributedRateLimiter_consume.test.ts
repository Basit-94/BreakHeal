import test from 'node:test';
import assert from 'node:assert/strict';
import { DistributedRateLimiter } from './rate.ts';

test('consume with unknown tier should not crash and should return a sensible result', () => {
  const limiter = new DistributedRateLimiter();
  // The current code does `this.tiers.get(tier)!` which returns undefined for an unknown tier,
  // then accesses `config.capacity` which throws a TypeError.
  // A robust implementation should either throw a clear error or fall back to a default tier.
  // We assert that it does NOT throw a TypeError (i.e., it handles the missing tier gracefully).
  let result: any;
  let threw = false;
  try {
    result = limiter.consume('client1', 'nonexistent-tier', 1, 1000);
  } catch (e) {
    threw = true;
    // If it throws, it must not be a TypeError from accessing property of undefined
    assert.ok(
      !(e instanceof TypeError),
      `Should not throw TypeError for unknown tier, but got: ${e.message}`
    );
  }
  // The test fails if a TypeError was thrown (which is the current buggy behavior)
  assert.equal(threw, false, 'consume with unknown tier should not throw TypeError');
});