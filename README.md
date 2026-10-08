# ModelLab

**Port:** 8005  
**Folder:** `05-modellab/`  
**Original PRDs:** 08 TuneLab · 09 MemOS  
**Acceptance:** M1–M11

Dataset → train/val split → LoRA-style checkpoints on disk → honest base vs prompt vs tuned eval → registry → inference. Separate three-tier memory (working / episodic / semantic).

## Install

Python 3.13 is used by Docker; 3.12–3.14 work locally. Do not copy `node_modules`, `.venv`, or `__pycache__` — recreate them here.

```bash
cd 05-modellab
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
```

Runtime dependencies are in `requirements.txt`; test dependencies are in `requirements-dev.txt`.

## Run locally (mock, no Docker)

```bash
cd 05-modellab
source .venv/bin/activate
OTEL_SDK_DISABLED=true python -m app.run
# or, with reload:
OTEL_SDK_DISABLED=true uvicorn app.api.main:app --host 0.0.0.0 --port 8005 --reload --no-access-log
```

Open http://localhost:8005/ for the streaming playground, http://localhost:8005/docs for the API, and `GET /health`. Use a **single worker**: streams and rate limits live in process memory.

## Run with Docker

From this folder, so other projects stay outside the build context:

```bash
docker build -t modellab .
docker run --rm -p 8005:8005 modellab
curl http://localhost:8005/health
```

The monorepo's compose service was not changed or exercised here. The image runs as a non-root user with one Uvicorn worker, copies only `app/` and runtime requirements, and health-checks `/health` on the actual `PORT`.

## Test

```bash
cd 05-modellab
source .venv/bin/activate
pytest
```

139 tests, ~90% coverage (the original 70% gate is kept). Streaming has three layers: store-level tests on an injected clock, HTTP tests, and **live-socket** tests (a real Uvicorn server, real mid-stream disconnects). See `VERIFICATION.md`.


## API

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/v1/datasets/validate` | Clean + schema check |
| POST | `/v1/datasets` | Ingest, 80/20 split (seed 42) |
| GET | `/v1/datasets/{id}` | Counts |
| POST | `/v1/training/run` | 3 checkpoints under `CHECKPOINT_DIR` |
| GET | `/v1/models` | Registry (GPU stub) |
| POST | `/v1/models/{id}/evaluate` | Includes “Did fine-tuning justify its cost?” |
| POST | `/v1/inference` | Lookup / base fallback |
| POST | `/v1/memory` | Add (`X-Tenant-Id`) |
| GET | `/v1/memory/search` | Ranked by relevance × recency × importance |
| GET | `/v1/memory/eval` | 20-query suite (pass if avg > 0.7) |
| GET | `/v1/memory/stats` | Tier counts |
| POST | `/v1/memory/compress` | Working-memory summary |

Config: `configs/lora.yaml`. Checkpoints in Compose: `/data/checkpoints`.

## Streaming

Resumable Server-Sent Events. **Tokens are simulated**: deterministic words derived from the prompt (and optional `model_id`). No model is called, and every token event carries `"simulated": true`.

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/v1/streams` | Create a stream; generation starts immediately and does not depend on any connection |
| GET | `/v1/streams/{id}` | Status, `last_event_id`, seconds until expiry |
| GET | `/v1/streams/{id}/events` | SSE. Resume with the `Last-Event-ID` header or `?last_event_id=N` |
| POST | `/v1/streams/{id}/cancel` | Stop a running stream; writes a terminal `cancelled` event |

```bash
curl -s -X POST localhost:8005/v1/streams -H 'content-type: application/json' \
  -d '{"prompt":"hello","max_tokens":20,"token_delay_ms":50}'
curl -N localhost:8005/v1/streams/<id>/events
curl -N localhost:8005/v1/streams/<id>/events -H 'Last-Event-ID: 7'   # events 8, 9, ...
```

Create body: `prompt` (1–2000 chars), `max_tokens` (1–512, default 48), `token_delay_ms` (0–250, default 40), `first_token_delay_ms` (0–60000, default 0; simulated time-to-first-token), optional `model_id` (must exist in the registry). Unknown fields are rejected. Validation errors never echo the prompt.

### Event stream

| Event | `id` | Meaning |
|-------|------|---------|
| `ready` | no | First frame of every connection: `resumed_after`, stream `status`. Also sets `retry: 1000`. |
| `token` | yes | `{"i": n, "token": "...", "simulated": true}` |
| `done` | yes | Terminal. `{"total_tokens", "sha256"}`, the digest of all token text concatenated |
| `cancelled` | yes | Terminal, same payload shape, for the tokens that were produced |
| `heartbeat` | **no** | `{"last_id", "status"}` while the stream is idle |

### Resume guarantees

- Event ids are consecutive integers from 1. Resuming after id *N* replays exactly events *N+1…* from a stored buffer, then follows live. No gaps, no duplicates, same bytes as an uninterrupted read.
- Generation is independent of connections: disconnect, wait, resume. The server never pauses or restarts it.
- Heartbeats are not stored and never carry an `id`, so they cannot move `Last-Event-ID`. They are sent every `STREAM_HEARTBEAT_SECONDS` of silence, including before the first token, and never after the terminal event.
- Resume point errors are decided **before** a 200 is sent: non-numeric, negative or oversized → 400/422; ahead of anything the stream has emitted → 400. Header wins over query when both are given.
- Resuming after the terminal event returns **204**, which makes `EventSource` stop reconnecting.
- Clients can check themselves: `done.sha256` is the SHA-256 of the concatenated token text and `total_tokens` the count. The playground does this and shows the result.

### Expiry and limits

- A stream becomes replayable when it finishes and is kept for `STREAM_TTL_SECONDS` (default 300). The window is **fixed**: reading or resuming does not extend it. Running streams never expire.
- Expired ids return **410 Gone**; ids never issued (or forgotten) return **404**. Expired entries are removed by a background reaper (every 15 s) and lazily on access, so memory is freed even if nobody asks again. A bounded tombstone list (1,024) is what distinguishes 410 from 404.
- Capacity: `STREAM_MAX_STORED` streams (503 + `Retry-After` when full; expiry frees slots), `STREAM_MAX_ACTIVE` concurrently generating, `STREAM_MAX_SUBSCRIBERS` connections per stream (429).
- Streams are in memory. A restart loses all of them; clients then see 404. Run one replica.

## Validation, tenants and limits

- Request bodies are validated: memory `text` 1–4000 chars, `importance` 0–1, `kind` one of working/episodic/semantic, `metadata` ≤ 2000 chars as JSON; search `q` 1–500 chars, `top_k` 1–50; `lora_r` 1–256, `lora_alpha` 1–1024, `base_model` ≤ 64 safe characters; `/v1/inference` takes only `model_id` and `prompt` (≤ 4000 chars); datasets ≤ 5000 rows. Error responses never echo submitted values.
- `X-Tenant-Id` must be 1–64 characters of letters, digits, `_`, `.`, `-` (otherwise 400). Reads, semantic dedup, the working-memory cap (20) and `/v1/memory/compress` are all per tenant. Without the header you are tenant `default`.
- Everything is bounded because the service is public and in-process: at most 5,000 episodic and 2,000 semantic entries (oldest dropped), 500 working entries overall, and `MAX_DATASETS` / `MAX_MODELS` (50 each, oldest evicted, evicted models' checkpoint files are deleted). Models keep their own held-out rows, so evaluation still works after their dataset is evicted.
- `GET /v1/models/{id}` and `/v1/models` never return the training lookup or held-out rows.
- `/v1/memory/eval` runs in a private tenant and never touches real memory.
- `/v1/datasets/validate` and `/v1/datasets` report how many rows were dropped as incomplete.
- Tracing exports only when `OTEL_EXPORTER_OTLP_ENDPOINT` is set; otherwise spans are no-ops (no connection attempts to localhost).
- Shutdown: on SIGTERM, open event streams receive a `shutdown` event and end immediately, so a redeploy is not held for the graceful-shutdown timeout. `EventSource` reconnects on its own with `Last-Event-ID`.

## Playground

`/` is a dependency-free page (vanilla HTML/CSS/JS, local fonts, strict CSP) over this API. **Drop connection** closes the socket mid-stream while the server keeps generating; **Resume** reconnects from the last id the page applied. It shows the last event id, resume count, heartbeats, and a live countdown to expiry, then verifies the final text against the server's checksum. Reloading the page replays the stored stream, or explains that it expired. The **Model lab** panel runs the real dataset → train → evaluate pipeline on a sample dataset, shows the honest base / prompted / tuned comparison, and can seed the next stream with the trained model.

## Request guard

Pure ASGI middleware (it never buffers SSE): POST bodies are capped (default 256 KiB, `MAX_BODY_BYTES`), nesting is limited to 32 levels, slow bodies time out after 10 s, POSTs are rate-limited per peer IP and globally in rolling 60-second windows, and responses carry `nosniff`, `no-referrer`, a restrictive CSP, and `no-store`. `GET` requests, including streams, are not rate-limited; Uvicorn caps concurrent connections at 64.

## Environment variables

No required variables or secrets.

| Variable | Default | Purpose |
| --- | --- | --- |
| `PORT` | `8005` | HTTP port; Railway injects this. |
| `STREAM_TTL_SECONDS` | `300` | How long a finished stream stays replayable. |
| `STREAM_HEARTBEAT_SECONDS` | `10` | Idle time before a heartbeat. |
| `STREAM_MAX_STORED` | `256` | Stored streams (running + replayable). |
| `STREAM_MAX_ACTIVE` | `32` | Streams generating at once. |
| `STREAM_MAX_SUBSCRIBERS` | `8` | Connections per stream. |
| `MAX_DATASETS` / `MAX_MODELS` | `50` / `50` | Registry caps; oldest evicted. |
| `CHECKPOINT_DIR` | `/tmp/checkpoints` | Where checkpoint files are written. |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | unset | Enables trace export. |
| `RATE_LIMIT_PER_MINUTE` | `60` | POSTs per peer IP per rolling minute. |
| `RATE_LIMIT_GLOBAL_PER_MINUTE` | `180` | POSTs per instance per rolling minute. |
| `MAX_BODY_BYTES` | `262144` | Request body cap. |
| `TRUSTED_PROXY_IPS` | `127.0.0.1` | Proxies whose forwarded headers Uvicorn trusts. Never `*` on a public service. |
| `OTEL_SDK_DISABLED` | unset | Set `true` to disable tracing export. |

## Railway deployment from the monorepo

1. Publish the monorepo to GitHub (this workspace has no `.git`; do not push unrelated projects just to deploy this one).
2. Create a Railway service from the repo. In **Settings → Source**, set **Root Directory** to `/05-modellab` and **Railway Config File** to `/05-modellab/railway.json` (the path is relative to the repo root).
3. Keep **one replica**: streams and rate limits are per process.
4. Deploy, confirm `/health` passes, then **Generate Domain**. Railway proxies are not in `TRUSTED_PROXY_IPS` by default, so visitors share one per-IP allowance until you configure it with verified proxy addresses.
5. Verify: `curl --fail https://<domain>/health`, then create a stream and resume it with `Last-Event-ID`. Idle-timeout behaviour of the proxy is the reason heartbeats exist; keep `STREAM_HEARTBEAT_SECONDS` below it.

No deployment has been performed from this workspace.

## Honesty

Stream tokens are simulated, not model output. Training is a deterministic CPU mock, not PEFT on a GPU. Tuned accuracy only hits items seen in train — the eval says so. Memory is in-process and tenant-scoped, not yet pgvector. Streams are in-process too: a restart loses them.
