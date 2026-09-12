export interface OrderItem {
    sku: string;
    unitPrice: number;
    quantity: number;
}

export type DiscountTier = 'STANDARD' | 'SILVER' | 'GOLD';

export interface OrderConfiguration {
    maxBatchSize: number;
    allowPartialFulfillment: boolean;
}

export class EnterpriseOrderService {
    private config: OrderConfiguration;
    private auditLog: string[] = [];

    constructor(config?: Partial<OrderConfiguration>) {
        this.config = {
            maxBatchSize: config?.maxBatchSize ?? 100,
            allowPartialFulfillment: config?.allowPartialFulfillment ?? false,
        };
    }

    public calculateAverageItemPrice(items: OrderItem[]): number {
        let totalCost = 0;
        let totalCount = 0;

        for (const item of items) {
            totalCost += item.unitPrice * item.quantity;
            totalCount += item.quantity;
        }

        if (totalCount === 0) {
            return 0;
        }

        return totalCost / totalCount;
    }
}
