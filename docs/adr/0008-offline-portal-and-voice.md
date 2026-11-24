# Portal agent and voice without a live browser or speech model

Phase 5 needs a legacy portal, a browser agent that recovers when a selector moves, and a claim-status voice path with a published latency. The test gate still forbids network and model calls. Playwright's browser download and the Whisper and Piper containers are network services.

## Decision

The portal keeps the three layouts and the hidden injection field. A signed-in flow adds login throttling, a 30-minute session, a confirmation page, and one slow response. The note write stays on the existing idempotency machine. There is no new database table.

The agent logs in from `deploy/env.example`, fills the stable field, and asks the model only when that field is missing. The model may propose `fill` or `read`. Any other action escalates, and the note is not saved. After save, the agent re-reads the page and keeps before and after images. Tests drive this through Flask's in-process client.

Voice accepts a synthetic utterance, returns a short acknowledgement, then reads the claim status. A noisy utterance is repeated instead of acted on. Audio is not kept. The published p50 and p95 are timings of this local path.

## Consequences

The 30 portal tasks and the voice bounds are properties of the offline stand-ins. They are not a Playwright success rate and not a faster-whisper word-error rate. Those containers remain available in the Compose voice profile for a later live run.
