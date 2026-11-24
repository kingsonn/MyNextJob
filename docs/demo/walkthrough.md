# Eight-minute walkthrough

Run `python -m services.demo` and open http://127.0.0.1:8080. Sign in with the admin token from `deploy/env.example`. The rehearsal of the same eight beats, without a browser, is `python -m pytest tests/unit/test_phase6.py`.

| Minute | What you do | What it shows |
| --- | --- | --- |
| 0 to 1 | Say that a status question speaks "Let me pull that up" before the status | Fast path, then slow path |
| 1 to 2 | Open Traces, then the demo trace | Policy lookup is in the step list, and the loss is outside the window |
| 2 to 3 | Explain the payout above the adjuster's limit | The payout is proposed and not sent until an adjuster token is present |
| 3 to 4 | Point at the 20-retry beat | One write |
| 4 to 5 | Point at the crash beat | The stored payout is kept and not repeated |
| 5 to 6 | Show the hidden portal instruction in the trace text | It is flagged and it is not a tool call |
| 6 to 7 | The portal beat saves one note and keeps two images | The browser steps are scripted, and the save is checked |
| 7 to 8 | The pool beat | The first provider returns 503 and the spare provider answers |

If a live model is down, nothing in this walkthrough changes. The demo does not call one.
