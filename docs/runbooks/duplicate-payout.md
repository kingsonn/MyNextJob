# Duplicate payout

1. Stop further execute calls for that claim.
2. Look up the idempotency key. A succeeded row is the one payout.
3. If the row is `in_progress` and the payment exists, reconcile. Do not insert again.
4. The crash suite is 50 seeded trials. Each one ends with one payout write.
