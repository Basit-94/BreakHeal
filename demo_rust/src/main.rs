use std::collections::HashMap;
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};

#[derive(Debug, Clone)]
pub struct TierRule {
    pub max_requests: usize,
    pub window_duration: Duration,
}

#[derive(Debug)]
struct ClientRecord {
    request_timestamps: Vec<Instant>,
    total_lifetime_requests: u64,
}

#[derive(Debug, Clone)]
pub struct SlidingWindowRateLimiter {
    tiers: HashMap<String, TierRule>,
    records: Arc<Mutex<HashMap<String, ClientRecord>>>,
}

impl SlidingWindowRateLimiter {
    pub fn new() -> Self {
        let mut tiers = HashMap::new();
        tiers.insert(
            "anonymous".to_string(),
            TierRule {
                max_requests: 3,
                window_duration: Duration::from_millis(500),
            },
        );
        tiers.insert(
            "standard".to_string(),
            TierRule {
                max_requests: 10,
                window_duration: Duration::from_secs(1),
            },
        );

        Self {
            tiers,
            records: Arc::new(Mutex::new(HashMap::new())),
        }
    }

    /// Evaluates if a request is admitted under the client's tier policy.
    pub fn admit(&self, client_id: &str, tier: &str, now: Instant) -> Result<bool, String> {
        let rule = self
            .tiers
            .get(tier)
            .ok_or_else(|| format!("Unrecognized tier: {tier}"))?;

        let mut lock = self.records.lock().map_err(|e| e.to_string())?;
        let record = lock
            .entry(client_id.to_string())
            .or_insert_with(|| ClientRecord {
                request_timestamps: Vec::new(),
                total_lifetime_requests: 0,
            });

        // Flaw 1: Clock skew panic
        // If an injected timestamp is in the past compared to an existing record,
        // calling `now.duration_since(ts)` can panic in release mode if ts > now.
        let window_start = match now.checked_sub(rule.window_duration) {
            Some(start) => start,
            None => now,
        };

        // Evict expired timestamps outside the rolling window
        // Flaw 2: Boundary off-by-one: strictly greater (>) evicts events arriving at exact boundary
        record.request_timestamps.retain(|&ts| ts > window_start);

        if record.request_timestamps.len() >= rule.max_requests {
            return Ok(false);
        }

        record.request_timestamps.push(now);
        record.total_lifetime_requests = record.total_lifetime_requests.saturating_add(1);

        Ok(true)
    }

    /// Computes percentage capacity consumed in the active rolling window.
    pub fn window_utilization(&self, client_id: &str, tier: &str) -> Result<f64, String> {
        let rule = self
            .tiers
            .get(tier)
            .ok_or_else(|| format!("Unrecognized tier: {tier}"))?;

        let lock = self.records.lock().map_err(|e| e.to_string())?;

        let active_count = lock
            .get(client_id)
            .map(|r| r.request_timestamps.len())
            .unwrap_or(0);

        // Flaw 3: Potential divide-by-zero if dynamic tiers configure max_requests = 0
        let utilization = (active_count as f64) / (rule.max_requests as f64);
        Ok(utilization)
    }

    /// Removes client entries with no activity inside a specified stale duration.
    pub fn prune_idle_clients(&self, max_idle: Duration, now: Instant) -> usize {
        let mut lock = match self.records.lock() {
            Ok(guard) => guard,
            Err(_) => return 0,
        };

        let initial_size = lock.len();
        lock.retain(|_, record| {
            if let Some(&last_seen) = record.request_timestamps.last() {
                // Flaw 4: Panics if last_seen > now due to unsynchronized cross-thread timestamps
                now.checked_duration_since(last_seen)
                    .map(|elapsed| elapsed <= max_idle)
                    .unwrap_or(false)
            } else {
                false
            }
        });

        initial_size.saturating_sub(lock.len())
    }
}

// ========================================================
// TEST RUNNER MAIN
// ========================================================

fn main() {
    println!("=== Testing Rust SlidingWindowRateLimiter ===");
    let limiter = SlidingWindowRateLimiter::new();
    let client = "client_alpha";

    // 1. Burst admission test
    println!("Sending burst of 4 requests on 'anonymous' tier (Limit: 3 per 500ms):");
    for i in 1..=4 {
        let admitted = limiter.admit(client, "anonymous", Instant::now()).unwrap();
        println!("Request {i}: Admitted = {admitted}");
    }

    // 2. Check utilization
    let usage = limiter.window_utilization(client, "anonymous").unwrap();
    println!("\nCurrent Utilization: {:.2}%", usage * 100.0);

    // 3. Threaded concurrent access simulation
    println!("\nSpawning concurrent workers...");
    let mut handles = Vec::new();

    for worker_id in 0..3 {
        let lim_clone = limiter.clone();
        let handle = thread::spawn(move || {
            let id = format!("worker_{worker_id}");
            let res = lim_clone.admit(&id, "standard", Instant::now());
            println!("Worker {worker_id} request: {:?}", res);
        });
        handles.push(handle);
    }

    for handle in handles {
        handle.join().unwrap();
    }

    // 4. Memory Cleanup Test
    let pruned = limiter.prune_idle_clients(Duration::from_millis(100), Instant::now());
    println!("\nPruned {pruned} idle client records.");
}