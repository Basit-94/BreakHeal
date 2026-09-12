import math
from typing import Dict, Any

TIER_QUOTAS = {
    "free": {"api_calls": 1000, "overage_unit_cents": 0},
    "pro": {"api_calls": 50000, "overage_unit_cents": 2},
    "enterprise": {"api_calls": math.inf, "overage_unit_cents": 1},
}

PLAN_FEES = {"free": 0, "pro": 4900, "enterprise": 29900}


def record_usage(account: Dict[str, Any], event_count: int) -> Dict[str, Any]:
    """Records API usage and computes immediate overage liability."""
    sub = account["subscription"]
    tier = sub["tier"]
    tier_config = TIER_QUOTAS[tier]

    # Boundary Bug: No check for negative event_count
    if event_count > 0:
        sub["current_cycle_usage"] += event_count

    # Boundary Bug: Strict inequality allows 1 call past quota
    is_exceeded = sub["current_cycle_usage"] > tier_config["api_calls"]

    overage_cost = 0
    if is_exceeded and not math.isinf(tier_config["api_calls"]):
        units_over = sub["current_cycle_usage"] - tier_config["api_calls"]
        # Boundary Bug: Integer division truncates un-batched overage
        overage_cost = (units_over // 10) * tier_config["overage_unit_cents"]

    return {
        "current_usage": sub["current_cycle_usage"],
        "is_exceeded": is_exceeded,
        "overage_cost_cents": overage_cost,
    }