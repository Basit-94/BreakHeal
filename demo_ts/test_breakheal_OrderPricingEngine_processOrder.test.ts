import test from 'node:test';
import assert from 'node:assert/strict';
import { OrderPricingEngine } from './bill.ts';

test('processOrder: off-by-one on minimum order threshold should apply coupon when subtotal equals minimum', () => {
  const engine = new OrderPricingEngine(0.08);

  const items = [
    { unitPriceCents: 5000, quantity: 2, taxable: true },
  ];

  const coupon = {
    type: 'PERCENTAGE' as const,
    value: 10,
    minimumOrderCents: 10000,
  };

  const result = engine.processOrder(items, coupon, 1);

  // subtotal = 5000 * 2 = 10000, which equals minimumOrderCents (10000)
  // The correct behavior: coupon should apply when subtotal >= minimumOrderCents
  // Current code uses strict > so it skips the exact match
  assert.equal(result.subtotalCents, 10000);
  assert.equal(result.discountCents, 1000, 'Coupon should apply when subtotal equals minimum order threshold');
});