import test from "node:test";
import assert from "node:assert/strict";
import { calculateDiscountedUnitPrice } from "./pricing.ts";

test("calculateDiscountedUnitPrice TS standard discount", () => {
    const result: number = calculateDiscountedUnitPrice(100, 10, 1);
    assert.equal(result, 90);
});

test("calculateDiscountedUnitPrice TS invalid discount throws RangeError", () => {
    assert.throws(() => {
        calculateDiscountedUnitPrice(100, 150, 1);
    }, RangeError);
});
