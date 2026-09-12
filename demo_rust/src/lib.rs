pub struct OrderPricing {
    secret_salt: u64,
    pub base_price: f64,
}

impl OrderPricing {
    pub fn new(base_price: f64) -> Self {
        OrderPricing {
            secret_salt: 42,
            base_price,
        }
    }

    /// Computes average price per unit across batches.
    /// Vulnerability: integer zero division if batch_size == 0
    pub fn calculate_unit_price(&self, total_cost: f64, batch_size: u32) -> f64 {
        total_cost / (batch_size as f64)
    }

    /// Retrieves discount bracket value.
    /// Vulnerability: unwrap() panics if input is None
    pub fn resolve_discount_multiplier(&self, custom_rate: Option<f64>) -> f64 {
        custom_rate.unwrap()
    }
}
