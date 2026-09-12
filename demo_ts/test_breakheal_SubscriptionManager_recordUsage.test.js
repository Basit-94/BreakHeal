import test from 'node:test';
import assert from 'node:assert/strict';
import { SubscriptionManager } from './subsmanag.js';

test('recordUsage should reject non-positive eventCount to prevent usage subtraction', () => {
  const instance = new SubscriptionManager();
  const account = {
    subscription: {
      tier: 'basic',
      currentCycleUsage: 50,
    },
  };

  // Negative eventCount should be rejected, not subtracted from usage
  assert.throws(
    () => instance.recordUsage(account, -10),
    /eventCount/i,
    'Negative eventCount should throw an error'
  );

  // Zero eventCount should also be rejected
  assert.throws(
    () => instance.recordUsage(account, 0),
    /eventCount/i,
    'Zero eventCount should throw an error'
  );
});