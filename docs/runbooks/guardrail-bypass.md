# Guardrail bypass

1. Read the audit row for the actor, claim, and verdict.
2. Confirm whether the text is one of the published red-team misses.
3. Add the phrase to the input or context markers only if it does not appear in the benign set.
4. Re-run the red-team suite. Block rate stays at or above 90 percent, and the false-positive rate stays under 3 percent.
5. Do not answer the bypass by widening a prompt.
