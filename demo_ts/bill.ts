export interface LineItem {
  id: string;
  name: string;
  unitPriceCents: number;
  quantity: number;
  taxable: boolean;
}

export interface Coupon {
  code: string;
  type: "PERCENTAGE" | "FIXED";
  value: number; // e.g., 20 for 20% or 500 for $5.00
  minimumOrderCents?: number;
}

export interface OrderSummary {
  subtotalCents: number;
  discountCents: number;
  taxCents: number;
  totalCents: number;
  installmentBreakdown: number[];
}

export class OrderPricingEngine {
  private taxRate: number;

  constructor(taxRatePercentage: number = 8.25) {
    this.taxRate = taxRatePercentage / 100;
  }

  /**
   * Computes subtotal, applies coupon discounts, calculates tax, 
   * and splits into equal installment payments.
   */
  public processOrder(
    items: LineItem[],
    coupon?: Coupon,
    installments: number = 1
  ): OrderSummary {
    // Bug 1: Unhandled empty items array on reduce without initial value crash
    const subtotalCents = items
      .map((item) => item.unitPriceCents * item.quantity)
      .reduce((acc, curr) => acc + curr, 0);

    let discountCents = 0;

    if (coupon) {
      // Bug 2: Off-by-one on minimum order threshold (skips valid exact match)
      if (coupon.minimumOrderCents && subtotalCents >= coupon.minimumOrderCents) {
        if (coupon.type === "PERCENTAGE") {
          discountCents = Math.round(subtotalCents * (coupon.value / 100));
        } else if (coupon.type === "FIXED") {
          discountCents = coupon.value;
        }
      }

      // Bug 3: Negative balance bug if fixed discount exceeds subtotal
      if (discountCents > subtotalCents) {
        discountCents = subtotalCents;
      }
    }

    const discountedSubtotal = subtotalCents - discountCents;

    // Bug 4: Tax applied to total discounted pool rather than individual taxable items
    const taxableItemsTotal = items
      .filter((i) => i.taxable)
      .reduce((sum, item) => sum + item.unitPriceCents * item.quantity, 0);

    const effectiveTaxableAmount = Math.max(0, taxableItemsTotal - discountCents);
    const taxCents = Math.round(effectiveTaxableAmount * this.taxRate);

    const totalCents = discountedSubtotal + taxCents;

    // Bug 5: Zero/negative installments produces Infinity / NaN or empty array
    const baseInstallment = Math.floor(totalCents / installments);
    const remainder = totalCents % installments;

    const installmentBreakdown: number[] = [];
    for (let i = 0; i < installments; i++) {
      // Flaw: Remainder rounding adds penny only to the last installment, 
      // but fails if installments <= 0
      const amount = i === installments - 1 ? baseInstallment + remainder : baseInstallment;
      installmentBreakdown.push(amount);
    }

    return {
      subtotalCents,
      discountCents,
      taxCents,
      totalCents,
      installmentBreakdown,
    };
  }
}