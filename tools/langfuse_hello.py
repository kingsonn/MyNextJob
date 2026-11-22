"""Send one hello-world trace to self-hosted Langfuse.

This script is not imported by pytest.
"""

from __future__ import annotations

import os
import time


def main() -> None:
    from generator.localenv import load_local_env

    load_local_env()
    public_key = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
    secret_key = os.environ.get("LANGFUSE_SECRET_KEY", "")
    host = os.environ.get("LANGFUSE_HOST", "")
    if not public_key or not secret_key or not host:
        raise SystemExit("Langfuse host and keys are missing. See deploy/env.example.")

    from langfuse import get_client

    client = get_client()
    with client.start_as_current_observation(as_type="span", name="phase0-hello") as observation:
        observation.update(output={"message": "phase 0 hello"})
        trace_id = observation.trace_id
    client.flush()
    if not isinstance(trace_id, str) or not trace_id:
        raise SystemExit("Langfuse did not return a trace id.")

    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        page = client.api.observations.get_many(trace_id=trace_id, name="phase0-hello", limit=1)
        rows = getattr(page, "data", None)
        if isinstance(rows, list) and rows:
            print(f"Langfuse trace confirmed: {trace_id}")
            return
        time.sleep(3)
    raise SystemExit(f"Trace {trace_id} was not visible via the Langfuse API.")


if __name__ == "__main__":
    main()
