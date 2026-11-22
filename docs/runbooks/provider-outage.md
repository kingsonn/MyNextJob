# Provider outage

1. Read the pool events. A 429 or 5xx cools that provider and the next healthy one is tried.
2. If every provider is down, hand off. Do not raise to the caller.
3. Leave the provider disabled until the cooldown time has passed.
