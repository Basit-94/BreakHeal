import test from 'node:test';
import assert from 'node:assert/strict';
import { EnterpriseOrderService } from './order_service.ts';

test('calculateAverageItemPrice should handle empty items array without returning NaN', () => {
    const instance = new EnterpriseOrderService();
    const result = instance.calculateAverageItemPrice([]);
    assert.notEqual(result, NaN, 'calculateAverageItemPrice should not return NaN for an empty items array');
    assert.ok(Number.isFinite(result), 'calculateAverageItemPrice should return a finite number for an empty items array');
});