# ModelLab demo guide

## Prepare

Use a local checkout and sample data. Complete the [README setup](../README.md#quick-start) once. Then run from the repository root:

```bash
source .venv/bin/activate
unset DATABASE_URL DATABASE_URL_UNPOOLED OTEL_EXPORTER_OTLP_ENDPOINT
OTEL_SDK_DISABLED=true python -m app.run
```

In a second terminal:

```bash
curl -fsS http://localhost:8005/health
```

Expected: `{"status":"ok","service":"modellab"}`. Use localhost so browser checksum APIs are available. Do not use reload mode during replay demonstrations. Default port is 8005; use a free port with `PORT=18005 OTEL_SDK_DISABLED=true python -m app.run` if necessary and change the browser URL accordingly.

## Main walkthrough (about 3 minutes)

Open **http://localhost:8005/playground**.

| Step | Action / sample data | Expected result |
| --- | --- | --- |
| 1. Model experiment | Click **Train sample model**. The built-in 20 capital-city pairs include `capital of France → Paris` and `capital of Japan → Tokyo`. | 16 train / 4 validation rows, three mock checkpoints. Base/prompted/tuned scores all 0%; delta 0; “no” improvement. This honest result is intentional. |
| 2. Start | Prompt: `Explain why resumable streams need stable event ids.` Set Tokens **60**, Speed **Slow · 150 ms**, Pause **None**; click **Start stream**. | Random-looking deterministic lab words arrive, explicitly simulated; Last event id grows. Selected sample model seeds tokens, not a real response. |
| 3. Break and resume | After several tokens, click **Drop connection**. Wait about one second; click **Resume**. | Generation continued on the server. Output catches up; on completion the verdict reports 60 tokens, contiguous IDs and matching SHA-256. Terminal event ID is 61. |
| 4. Memory | Keep the generated Tenant ID. Note: `Stream replay uses stable event IDs.` Tier **Working**, Importance **0.8**; click **Save memory**. Search `stream replay`, with **All tiers**. | Saved note appears with tier/score/importance. Rank depends on text and age; do not promise a fixed score. A different tenant cannot retrieve this note. |
| 5. Show the contract | Open `/docs`, expand **GET /health**, click **Try it out**, then **Execute**. | HTTP 200 with the health JSON. `/redoc` offers searchable read-only reference; `/openapi.json` works without CDN assets. |

Optional: start another slow stream and **Cancel**, or choose a **15 s** first-token pause to show the default 10-second heartbeat. **Clear** empties only the browser connection log; it does not delete server data. Page reload replays the stored stream while it remains available.

For a quick terminal-only memory check, use a fresh tenant name:

```bash
curl -fsS -X POST http://localhost:8005/v1/memory \
  -H 'Content-Type: application/json' -H 'X-Tenant-Id: demo-terminal' \
  -d '{"text":"Stream replay uses stable event IDs.","kind":"working","importance":0.8}'
curl -fsS 'http://localhost:8005/v1/memory/search?q=stream%20replay' \
  -H 'X-Tenant-Id: demo-terminal'
```

## 60-second pitch

> ModelLab is a small developer lab for three behaviors that are easy to hide in an AI demo: model evaluation, memory ranking, and connection recovery. First, a sample dataset is split into training and validation rows. The mock trainer creates checkpoints, and evaluation shows whether its answer lookup improved on held-out data. Next, notes are stored in three memory tiers and retrieved by relevance, recency, and importance. Finally, we deliberately disconnect a token stream. The server keeps generating; reconnecting replays missed events, and a checksum proves the final output is intact. Training and tokens are simulations, so this project demonstrates engineering behavior without claiming model quality or needing a GPU. It runs locally without external API keys; an optional database preserves datasets, models, and memory.

Technical explanation: vanilla browser controls call a single FastAPI process. Model/memory operations use bounded stores; an asyncio task writes tokens to a replay buffer independently of sockets. `Last-Event-ID` or its query equivalent selects the replay suffix. Optional PostgreSQL saves snapshots, not stream buffers.

## Recovery and verified limits

| Failure | Recovery |
| --- | --- |
| Server unavailable / port occupied | Check terminal output; use a free `PORT`, then use that URL. Confirm health says `service: modellab`, not another app. |
| Dataset/model/checkpoint error | Use the sample button again; ensure `CHECKPOINT_DIR` is writable. |
| Replay 404 or 410 | Server restarted or stream expired; start a new stream. Default finished-stream replay window: 300 s. |
| HTTP 429 / 503 | Wait for the retry window; avoid repeated POSTs and excess open streams. |
| Memory result missing | Keep the same Tenant ID and search tier; local restart clears memory without a database. |
| `/docs` or `/redoc` blank | Check internet/CDN access; demonstrate the workspace and fetch `/openapi.json` instead. |
| Checksum unavailable | Use localhost or HTTPS; the page still checks token count/order but does not claim a hash match. |
| Configured database is unreachable | For this local demo, unset database variables; do not change production settings. |

Verified 2026-10-12 on Python 3.14.4: 153 tests passed, 90.19% coverage; static build, dependency check and JS syntax passed. The documented `python -m app.run` startup was also exercised on port 18005 with database/export variables unset. Real local HTTP walkthrough verified sample training/evaluation, known-answer inference, a 60-token disconnect after event 3 with matching SHA-256, memory add/search/compression/evaluation, and all four HTML routes. Existing GitHub **Verify** run for `c6446a3` succeeded. The browser preview disconnected, so this pass did not complete the UI walkthrough. Fresh installation, Docker (daemon unavailable), live PostgreSQL, live OTLP export and production health were not verified. No app code, production data or paid services were changed.
