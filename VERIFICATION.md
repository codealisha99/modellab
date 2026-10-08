# Verification — 2026-10-09

_Updated after a hardening pass; see the last section._

Scope: the streaming interface (resume, heartbeats, expiry), the request guard, and the playground. Stream tokens are **simulated**; none of this verifies model quality.

## Automated checks

- `pytest`: **139 passed**, **90% coverage** (70% gate retained). `streaming/store.py` 99%, `streaming/routes.py` 100%. Host Python 3.14.4; `pip check` clean.
- Same suite inside `python:3.13-slim` (the production base): **139 passed** (re-run on 3.13 earlier at 93; the 46 hardening tests were added after).
- Five consecutive runs, two of them with 8 CPU-spinning processes competing: no failures or flakes (timing tests use wide margins, e.g. heartbeat 0.1 s vs 0.25 s token gaps).
- Dependency pins were moved to the SchemaGuard set (`fastapi 0.135.4`, `pydantic 2.12.5`, …). The previous pins did not build on Python 3.14. The 11 pre-existing tests pass unchanged. `numpy` and `redis` were dropped because nothing imports them.

### Three layers, on purpose

1. **Store tests** (`test_streaming_store.py`, injected fake clock): the SSE generator is driven directly, so a "disconnect" is an exact `aclose()`.
2. **HTTP tests** (`test_streaming_api.py`): status codes, headers, validation, guard.
3. **Live-socket tests** (`test_streaming_live.py`): real Uvicorn thread, real `httpx` streaming, connections dropped mid-stream. `TestClient` buffers whole responses and cannot prove incremental delivery or survive a dropped socket, so it is not relied on for those claims.

### Resume correctness

- For **every** cut point 0…21 of a 20-token stream: read *k* events, disconnect, resume from *k*. The concatenation equals the uninterrupted stream event for event (id, type, payload), with no duplicates.
- Resume while the producer is still running, four disconnects in a row; resume after every single event with heartbeats interleaved; resume during the pre-first-token pause.
- Real sockets: four drops at awkward positions, then a final resume; result is identical to a fresh uninterrupted read, with `done.sha256` matching the reassembled text.
- Header vs `?last_event_id=` (header wins), 204 once the terminal event is seen, 400 for malformed or ahead-of-stream ids (rejected before a 200 is committed), cancel (including before the producer task ever runs).
- The server frees its per-stream connection slot after a client drops (`subscribers` returns to 0).

### Heartbeats

- Emitted during slow generation and during the pre-first-token pause; they carry no `id`; `last_id` is truthful; none after the terminal event.
- Tokens are delivered by notification, not by heartbeat timing: with a 30 s heartbeat interval, 40 fast tokens finish in well under 2 s (a lost-wakeup bug would take ~30 s per token).
- Through the guard middleware on a real socket, the first token arrives in <0.5 s of a ~1 s stream (not buffered).

### Expiry

- Fake clock: replayable at TTL−0.1 s, gone at exactly TTL; fixed (repeated reads do not extend it); running streams are never expired and the clock starts at completion; 410 vs 404; capacity freed on expiry; tombstones bounded at 1,024; a reader already attached when the entry expires still receives the rest of its replay.
- Background reaper removes expired streams with no access at all (asserted by inspecting the store).
- Real time on a live server: a stream is replayable inside a 1 s TTL, then returns 410, and is gone from the store.

### Mutation check

Ten deliberate bugs were injected into `store.py` one at a time; the suite failed for each: skip an event on resume, duplicate an event on resume, heartbeat carrying an `id`, no heartbeat, expiry off-by-one, TTL measured from creation, never expire, connection-slot leak, accept ahead-of-stream resume points, wrong checksum.

## Runtime checks with the real app (`python -m app.run`)

- `curl`: stream with a 5 s pause and 4 s heartbeat shows `ready`, a heartbeat at `last_id 0`, then tokens; connection killed after id 4; `Last-Event-ID: 3` replays 4–13 and `done`; `?last_event_id=0` returns all 13; terminal id → `204`; `99` → `400`; after the 45 s TTL → `410`; unknown id → `404`.
- Docker: image builds (Python 3.13-slim), runs as user `lab`, health check `healthy`. Inside the container (TTL 6 s, heartbeat 1 s): 2 heartbeats during a 2.5 s pause, replay `200` inside the TTL, `410` after.
- Browser (Cursor native preview): started a 100-token stream, dropped at id 22 while the server kept generating, resumed ("server replaying from id 23"); final status `Verified across 1 resume: 100 tokens, contiguous ids, SHA-256 matches the server`. A 5 s pause produced one heartbeat. The expiry countdown reached "expired" at the server's TTL; reloading then showed the 410 explanation. No horizontal overflow at the preview width. Text is rendered with `textContent` only; the CSP forbids inline scripts and remote origins.

## Not verified / known limits

- **No public deployment.** No Railway credentials were used; steps are in `README.md`.
- Single process only. Streams are lost on restart, and multiple replicas would not share them. Rate limits are likewise per process.
- Heartbeat interval must be shorter than any intermediary's idle timeout; that was not tested against a real proxy.
- The expiry window is fixed from completion; a client that is still reading at expiry is not cut off, but cannot resume afterwards.
- Only desktop-ish and the preview's narrow viewport were looked at; no cross-browser pass (Safari/Firefox `EventSource` behaviour not tested).
- The earlier inline dashboard on `/` (registry and memory JSON) was replaced by the playground because it relied on inline script, which the new CSP blocks. The same data remains at `/v1/models` and `/v1/memory/stats`, and in `/docs`.

## Hardening pass

An audit of the running service found real defects. Each has a regression test in `tests/test_hardening.py`; 43 of its 46 tests fail against the previous commit (the other three cover behaviour that already worked).

| Found | Effect | Fix |
| --- | --- | --- |
| `span()` swallowed exceptions then yielded twice | training on an unknown dataset returned **500** | exceptions propagate; 404 |
| `GET /v1/memory/eval` called `clear()` | any visitor could erase **all tenants' memory** | runs in a private tenant |
| Semantic dedup ignored tenants | returned **another tenant's memory** on a near-duplicate | dedup per tenant |
| Working cap, compress, stats were global | tenants evicted/exposed each other | per tenant |
| No bounds on memory, datasets, models, checkpoint files | unbounded memory/disk growth | caps with oldest-first eviction; checkpoint cleanup (path-checked) |
| `GET /v1/models/{id}` returned the training lookup | training data readable by id | removed from public views |
| Unvalidated bodies (`importance: 99`, `lora_r: -1`, `top_k: -5`, non-string prompt, any tenant header) | bad state, odd errors | typed, bounded models; tenant header pattern |
| Shutdown with a connected SSE client | hung 15 s, `CancelledError` traceback (would stall every redeploy) | `shutdown` event + immediate end |
| Default OTLP exporter pointed at `localhost:4318` | export errors in production | export only when an endpoint is configured |

Shutdown was measured on the real process and in Docker: **15 s → 0 s** locally, `docker stop` takes **1 s**, no traceback in logs, and the client receives `event: shutdown`.

Browser: the new Model lab panel trained and evaluated through the real API (honest result "no: +0.0 over base", because held-out rows were never seen in training), and a stream seeded by the trained model verified (`60 tokens … SHA-256 matches`). Desktop 1280 px layout measured: two columns, no horizontal overflow.

Still not covered: no authentication (datasets and models are shared across visitors, only memory is tenant-scoped); a single process; no public deployment.
