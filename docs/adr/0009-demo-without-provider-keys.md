# Demo without provider keys

Phase 6 needs a trace page, a rehearsed walkthrough, and a start path that works on a clean machine. The blueprint's live path uses free provider keys and Ollama. The test gate still forbids network calls, and a missing key must not block the demo.

## Decision

The demo server loads the synthetic book in memory and serves the admin pages plus one recorded trace. Replay uses the cassette. The eight-minute beats are a function, `rehearse`, so the walkthrough can be checked without a person at the keyboard.

No provider key, Ollama process, or Postgres connection is required to open the pages. `make up` remains the way to start Postgres, Redis, and the optional voice and Langfuse profiles.

## Consequences

The screens are the real console, backed by the same code the tests call. They are not a live-model transcript. The three-minute video is a script the operator records; the repository does not contain a media file.
