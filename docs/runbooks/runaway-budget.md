# Runaway budget

1. Confirm the session token cap and the tenant shadow cap in `services/gateway/reliability.yaml`.
2. A token overrun moves to the cheap tier, then a handoff.
3. A shadow-cost overrun tries the cache, then the cheap tier, then a handoff.
4. The loop breaker still applies: step cap, tool cap, repeated signature, and no progress.
