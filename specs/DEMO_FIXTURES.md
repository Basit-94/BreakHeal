# Demo Fixtures Specification — BreakHeal

## Overview
Demo scenarios located under `demo_repo/` for validating BreakHeal's end-to-end red-to-green pipeline.

## Fixture Scenarios
1. **Discount Calculator (`pricing.py`)**:
   - Flaw: Negative discount rate or division by zero when quantity is 0; fails on empty cart.
2. **Date Range Filter (`filters.py`)**:
   - Flaw: Off-by-one boundary inclusion (start date == end date).
3. **Session Token Parser (`auth.py`)**:
   - Flaw: Unhandled malformed tokens or missing padding causing unhandled exceptions.
