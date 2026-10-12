# ModelLab

<img src="app/static/icon.svg" width="64" height="64" alt="ModelLab checkpoint logo" />

ModelLab is a developer lab for deterministic CPU mock training, scored three-tier memory, and verifiable resumable streams. It helps developers inspect a dataset → train → evaluate workflow and test what happens when a streaming connection drops.

Created and maintained by [Alisha Karma](https://alishakarma.com) ([codealisha99](https://github.com/codealisha99)). Individual contributions remain recorded in Git history. For creator inquiries: [lishykarma99@gmail.com](mailto:lishykarma99@gmail.com).

Training and tokens are simulated; this is not a GPU training service. Memory uses deterministic hash embeddings. Tenant IDs separate namespaces but do not authenticate users: use sample data on the public demo.

## Install

Python 3.13 is used by Docker; 3.12–3.14 work locally. Do not copy `node_modules`, `.venv`, or `__pycache__` — recreate them here.

```bash
git clone https://github.com/codealisha99/modellab.git
cd modellab
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
```

Runtime dependencies are in `requirements.txt`; test dependencies are in `requirements-dev.txt`. If you already have a checkout, run the environment setup from its root instead of cloning again. The `private` field in `package.json` prevents npm publication; it does not indicate GitHub repository visibility.

## Run locally (mock, no Docker)

```bash
source .venv/bin/activate
OTEL_SDK_DISABLED=true python -m app.run
# or, with reload:
OTEL_SDK_DISABLED=true uvicorn app.api.main:app --host 0.0.0.0 --port 8005 --reload --no-access-log
```

Open http://localhost:8005/ for the overview and embedded playground, http://localhost:8005/playground for the dedicated workspace, http://localhost:8005/docs for interactive API docs, and http://localhost:8005/redoc for the reference. Health is available at `GET /health`. Use a **single worker**: streams and rate limits live in process memory.

## Run with Docker

From this folder, so other projects stay outside the build context:

```bash
docker build -t modellab .
docker run --rm -p 8005:8005 modellab
curl http://localhost:8005/health
```

The image runs as a non-root user with one Uvicorn worker, copies only `app/` and runtime requirements, and health-checks `/health` on the actual `PORT`.

## Test

```bash
source .venv/bin/activate
pytest
python3 scripts/build_frontend.py
for file in app/static/*.js; do node --check "$file"; done
```

The suite enforces a 70% coverage gate. Streaming has three layers: store-level tests on an injected clock, HTTP tests, and **live-socket** tests (a real Uvicorn server, real mid-stream disconnects). See `VERIFICATION.md`.

[Verification CI](.github/workflows/verify.yml) runs the Python suite, dependency consistency, JavaScript syntax checks, and static build on pushes and pull requests to `main`. Node.js is needed for JavaScript syntax checks; the application itself runs with Python.

## Architecture

| Location | Responsibility |
| --- | --- |
| `app/api/` | HTTP contracts, request limits, validation, and security headers |
| `app/training/` | Deterministic dataset, checkpoint, evaluation, and registry workflow |
| `app/memory/` | Bounded tenant namespaces and ranked memory retrieval |
| `app/streaming/` | Transient SSE generation, replay, expiry, and cancellation |
| `app/persistence.py` | Optional database snapshots with rollback on write failure |
| `app/frontend.py`, `app/templates/`, `app/static/` | Shared page renderer, product shell, styles, and browser controls |
| `tests/` | API, persistence, hardening, packaging, and live-socket regression checks |


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

`configs/lora.yaml` records sample training settings; the API accepts settings in the training request and does not automatically read that file. Checkpoints default to `/tmp/checkpoints`; set `CHECKPOINT_DIR` on the API host to change this.

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

`/` is a dependency-free page (vanilla HTML/CSS/JS, local fonts, strict CSP) over this API. **Drop connection** closes the socket mid-stream while the server keeps generating; **Resume** reconnects from the last id the page applied. It shows the last event id, resume count, heartbeats, and a live countdown to expiry, then verifies the final text against the server's checksum. Reloading the page replays the stored stream, or explains that it expired. The memory panel saves notes to working, episodic, and semantic tiers and retrieves scored matches using the existing API. A random tenant namespace is stored per tab; it is not an access credential. The **Model lab** panel runs the real dataset → train → evaluate pipeline on a sample dataset, shows the honest base / prompted / tuned comparison, and can seed the next stream with the trained model.

## Request guard

Pure ASGI middleware (it never buffers SSE): POST bodies are capped (default 256 KiB, `MAX_BODY_BYTES`), nesting is limited to 32 levels, slow bodies time out after 10 s, POSTs are rate-limited per peer IP and globally in rolling 60-second windows, and responses carry `nosniff`, `no-referrer`, a restrictive CSP, and `no-store`. `GET` requests, including streams, are not rate-limited; Uvicorn caps concurrent connections at 64.

## Environment variables

Local development requires no secrets. Copy `.env.example` as a reference for shell variables; the application does not automatically load `.env`. Production persistence uses `DATABASE_URL` and `DATABASE_URL_UNPOOLED` on the API host. Never expose database credentials in the frontend.

| Variable | Default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | unset | Neon pooled URL for durable datasets, models, and memory. |
| `DATABASE_URL_UNPOOLED` | unset | Direct Neon URL for idempotent startup schema initialization. |
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

## Existing deployment configuration

- Frontend: https://modellab-nine.vercel.app
- Railway API: https://api-production-b980.up.railway.app
- API docs: https://modellab-nine.vercel.app/docs
- GitHub: https://github.com/codealisha99/modellab

These are recorded deployment addresses, not a claim of current availability. Consult the dated audit reports for checks actually performed.

GitHub `main` is connected to both Railway and Vercel. Railway builds the root Dockerfile; Vercel packages the existing static playground using `scripts/build_frontend.py`. `vercel.json` proxies `/v1/*`, `/health`, and API documentation to Railway, keeping browser requests on the same origin. Database credentials belong only in Railway, never in Vercel or GitHub.

Keep exactly one Railway replica and one Uvicorn worker. Datasets, models, evaluation scores, and memory are committed to bounded JSONB snapshots in Neon; startup restores them and regenerates CPU mock checkpoint files on ephemeral disk. Failed database writes roll back the in-memory mutation. `/health` verifies database connectivity. Streams and rate limits remain transient and are lost on restart. This snapshot design is intended for this small demo, not multiple writers or a distributed deployment.

To deploy manually after testing:

```bash
pytest
# Publish the deployment changes to the connected main branch.
git push origin main
# Or deploy the current checkout directly:
railway up --service api --detach
vercel deploy --prod --yes
```

Use `railway deployment list --service api` and `vercel inspect <deployment-url>` to check rollout status. Smoke-test `/health`, train a sample model, and verify stream delivery and resume through the Vercel URL.

## Honesty

Stream tokens are simulated, not model output. Training is a deterministic CPU mock, not PEFT on a GPU. Tuned accuracy only hits items seen in train — the eval says so. Memory is tenant-scoped with deterministic hash embeddings, not pgvector. With `DATABASE_URL`, datasets, models, and memory persist in Neon; without it, they remain in-process. Streams are in-process too: a restart loses them.

## Frontend design and verification

The overview, experiment workspace, interactive documentation, reference, and HTML 404 use a consistent shell. The FastAPI pages and Vercel static output share the renderer in `app/frontend.py` and templates in `app/templates/`. Semantic tokens live in `app/static/tokens.css`; component and responsive styles live in `app/static/style.css`. Fonts are served locally. API documentation uses pinned Swagger UI and ReDoc CDN assets, with a small Swagger plugin that keeps endpoint links outside disclosure buttons.

Build the static output with `python3 scripts/build_frontend.py`. This regenerates the ignored `public/` directory. See [DESIGN_SYSTEM.md](DESIGN_SYSTEM.md) for styling conventions and [AUDIT_REPORT.md](AUDIT_REPORT.md) for the redesign scope, tests, and remaining verification limits.

## Project lineage

The original TuneLab training and MemOS memory requirements were consolidated into ModelLab. The implementation remains a deterministic CPU demo, as described in [PRD.md](PRD.md). Historical commit identities and third-party font licenses are preserved. See [CONTRIBUTING.md](CONTRIBUTING.md) for maintainer and validation guidance.

## Ownership and licensing

ModelLab keeps its product identity separate from the creator attribution above. There is no project-wide LICENSE file; this repository does not declare a project-wide open-source license. Font and dependency notices remain in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). See the [ownership and branding audit](docs/audits/ownership-branding-2026-10-12.md) for current findings and verification limits.
