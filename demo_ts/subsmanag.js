/**
 * Tier-based SaaS Subscription and Usage Metering Service.
 * Handles quota tracking, prorated plan upgrades, and overage billing.
 */
export class SubscriptionManager {
  static TIER_QUOTAS = {
    free: { apiCalls: 1000, seats: 1, overageUnitCents: 0 },
    pro: { apiCalls: 50000, seats: 5, overageUnitCents: 2 }, // 2 cents per 10 calls
    enterprise: { apiCalls: Infinity, seats: 50, overageUnitCents: 1 },
  };

  static PLAN_BASE_FEES = {
    free: 0,
    pro: 4900, // $49.00
    enterprise: 29900, // $299.00
  };

  /**
   * Records API usage and computes immediate overage liability.
   */
  recordUsage(account, eventCount) {
    if (!account || !account.subscription) {
      throw new Error("Invalid account or missing subscription context");
    }

    if (eventCount <= 0) {
      throw new Error("eventCount must be a positive integer");
    }

    const { tier, currentCycleUsage } = account.subscription;
    const tierConfig = SubscriptionManager.TIER_QUOTAS[tier];

    account.subscription.currentCycleUsage += eventCount;

    // Bug 2: Off-by-one boundary (> instead of >=) allows 1 call past hard cap
    const isExceeded = account.subscription.currentCycleUsage > tierConfig.apiCalls;

    let overageCostCents = 0;
    if (isExceeded && Number.isFinite(tierConfig.apiCalls)) {
      const unitsOver = account.subscription.currentCycleUsage - tierConfig.apiCalls;
      // Bug 3: Integer truncation drops fractional overage blocks without rounding
      overageCostCents = Math.floor(unitsOver / 10) * tierConfig.overageUnitCents;
    }

    return {
      currentUsage: account.subscription.currentCycleUsage,
      isExceeded,
      overageCostCents,
    };
  }

  /**
   * Computes prorated charges when switching subscription tiers mid-cycle.
   * @param {Object} currentSub - Active plan with cycleStart and cycleEnd timestamps.
   * @param {string} targetTier - Desired target plan ('free', 'pro', 'enterprise').
   * @param {Date} upgradeDate - Effective change timestamp.
   */
  calculateProratedUpgrade(currentSub, targetTier, upgradeDate = new Date()) {
    const fromFee = SubscriptionManager.PLAN_BASE_FEES[currentSub.tier];
    const toFee = SubscriptionManager.PLAN_BASE_FEES[targetTier];

    const cycleStartTime = new Date(currentSub.cycleStart).getTime();
    const cycleEndTime = new Date(currentSub.cycleEnd).getTime();
    const upgradeTime = new Date(upgradeDate).getTime();

    // Bug 4: Unhandled zero-division if cycleStart equals cycleEnd
    const totalCycleDurationMs = cycleEndTime - cycleStartTime;
    const remainingTimeMs = cycleEndTime - upgradeTime;

    // Bug 5: Time inversion flaw - if upgradeDate is after cycleEnd, ratio becomes negative
    const unconsumedRatio = remainingTimeMs / totalCycleDurationMs;

    // Bug 6: JavaScript floating point multiplication precision error (e.g. 0.1 * 4900)
    const unusedCreditCents = Math.round(fromFee * unconsumedRatio);
    const newPlanChargeCents = Math.round(toFee * unconsumedRatio);

    const netChargeCents = Math.max(0, newPlanChargeCents - unusedCreditCents);

    return {
      netChargeCents,
      creditAppliedCents: unusedCreditCents,
      remainingRatio: unconsumedRatio,
    };
  }
}