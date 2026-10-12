# API dependencies and configuration

**Local minimum: Python and the packages in `requirements.txt`. No external API, credentials, GPU or database is required.** Tests add `requirements-dev.txt`. The browser calls this project’s own `/health` and `/v1/*` routes; inspect `/openapi.json` for complete contracts.

## Runtime integrations

| Integration / purpose | Requirement and actual use | If unavailable | Environment / credentials and official docs |
| --- | --- | --- | --- |
| PostgreSQL via psycopg — durable datasets/models/memory | Optional locally; mandatory **if persistence is enabled**. Code uses generic PostgreSQL; recorded hosting uses Neon. Live DB was not tested here. | With no URL: volatile stores. With a configured bad URL: startup/writes/health fail; no silent fallback. | `DATABASE_URL`; optional `DATABASE_URL_UNPOOLED` for startup initialization, otherwise main URL is used. Get database/user credentials from your DBA or the Neon project **Connect** dialog. [PostgreSQL connection docs](https://www.postgresql.org/docs/current/libpq-connect.html), [Neon connection guide](https://neon.com/docs/connect/connect-from-any-app). |
| OTLP/HTTP collector — OpenTelemetry traces | Optional; installed SDK/exporter, activated only by the general endpoint when not disabled. No collector configured in local verification. | No remote traces; application workflows continue. | `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_SDK_DISABLED`. Authenticated collectors can use SDK `OTEL_EXPORTER_OTLP_HEADERS` or `OTEL_EXPORTER_OTLP_TRACES_HEADERS`; obtain endpoint/auth from your collector operator or tracing provider. [Exporter docs](https://opentelemetry.io/docs/languages/python/exporters/). |
| jsDelivr — Swagger UI 5.33.1 and ReDoc 2.5.4 assets | Used on `/docs` and `/redoc`; optional for the rest of the product. No account/key. | Interactive/reference renderers fail; local workspace and `/openapi.json` still work. | No env variables. [jsDelivr docs](https://www.jsdelivr.com/documentation), [Swagger UI](https://swagger.io/docs/open-source-tools/swagger-ui/usage/installation/), [ReDoc CE](https://redocly.com/docs/redoc/). `cdn.redoc.ly` and `fastapi.tiangolo.com` are documentation-asset CSP allowlists, not additional configured APIs. |
| Model/embedding provider | **Mocked/local, no external provider.** `phi-3-mini` is a metadata label; no weights are downloaded. Memory uses deterministic hash vectors. | Not applicable. | No model API key, Hugging Face token or GPU credentials. Simulated training cost/latency/memory are not real bills or benchmarks. |

Database role needs table-creation permission at startup plus read/write access to `modellab_state`. Only the API host should receive database credentials; never static output, browser JavaScript, logs or Git. The schema is initialized at startup; no separate migration runner exists.

The app appends `/v1/traces` to the collector endpoint if needed. Setting only `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` does not activate export because the app checks/passes the general endpoint explicitly. The installed SDK also accepts certificate, timeout and compression settings described in its official exporter docs; none are required locally. Tracing errors are tolerated and a fallback trace ID is not proof of collector delivery.

## Development and deployment services

| Service / purpose | Status and failure impact | Credentials / env and official docs |
| --- | --- | --- |
| PyPI / pip — pinned Python packages | Installation dependency; no runtime network call to PyPI. Offline install needs cached packages. | No credentials for public packages. [pip install](https://pip.pypa.io/en/stable/cli/pip_install/). |
| GitHub / Actions — source and verification | Existing remote and CI; optional for local run. Without it, cloning/hosted checks fail, not an existing checkout’s application. | Public clone needs no credential; pushes/private access need account authorization. CI uses platform-managed `GITHUB_TOKEN`, with read-only contents permission. No custom secret required. [Actions docs](https://docs.github.com/en/actions). |
| Node.js / npm | Node is used only for JS syntax verification; npm scripts are Python command wrappers, with no npm dependencies to install. | No API or credentials. [Node.js docs](https://nodejs.org/api/). |
| Docker / Docker Hub — optional container | `python:3.13-slim` base, non-root API runtime. Engine unavailable in local verification; image build/run unverified. | Public base image; no app-specific credentials. Registry login may be needed for provider limits. [Docker docs](https://docs.docker.com/). |
| Railway — configured API host | Optional deployment; `railway.json` builds Dockerfile. Configured Vercel API/docs proxies depend on the Railway host. Current production health not checked. | Deployment account/GitHub integration or CLI login; Railway supplies `PORT`. Configure database/OTLP variables on the API service if used. No `RAILWAY_TOKEN` is required by app code. [Railway variables](https://docs.railway.com/variables). |
| Vercel — configured static frontend/proxy | Optional deployment; builds ignored `public/`, proxies APIs/docs to `https://api-production-b980.up.railway.app`. Existing URL recorded as `https://modellab-nine.vercel.app`; availability not checked here. Static output alone does not include a backend. | Deployment account/GitHub integration or CLI login; no app API key or database variable on frontend. [Deployment docs](https://vercel.com/docs/deployments). For future diagnostics, install CLI with `npm i -g vercel`; no deployment is needed to demo locally. |

**Costs:** provider pricing/account plans were not verified in this audit; no dollar amounts or free-tier entitlement are assumed. Database hosting, collector hosting, CI/registry usage and deployments may incur provider charges. Local simulations call no paid model API. Obtain current terms from the official provider before provisioning; nothing was provisioned here. Personal website/GitHub/X/mailto footer links are not API integrations. Redis, pgvector, auth, payment, email delivery and analytics services are not wired into the application.

## Application environment variables

All are optional for the default local demo. Export them in the process environment: `.env.example` is not automatically loaded. Secrets are limited to optional database URLs and collector auth headers; do not print their values.

| Variable | Default / effect |
| --- | --- |
| `PORT` | `8005`; API listener (`app.run`, not the hardcoded npm dev command) |
| `CHECKPOINT_DIR` | `/tmp/checkpoints`; writable mock checkpoint path |
| `DATABASE_URL` | Unset; enables persistent snapshots when set |
| `DATABASE_URL_UNPOOLED` | Unset; optional direct startup/init connection when persistence is enabled |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | Unset; enables collector export unless disabled |
| `OTEL_SDK_DISABLED` | Unset; `true`, `1` or `yes` disables tracing |
| `OTEL_EXPORTER_OTLP_HEADERS` / `OTEL_EXPORTER_OTLP_TRACES_HEADERS` | Unset; SDK collector-auth headers, trace-specific takes precedence |
| `STREAM_TTL_SECONDS` | `300`; replay lifetime after stream completion |
| `STREAM_HEARTBEAT_SECONDS` | `10`; idle SSE heartbeat interval |
| `STREAM_MAX_STORED` | `256`; retained stream capacity |
| `STREAM_MAX_ACTIVE` | `32`; simultaneous producers |
| `STREAM_MAX_SUBSCRIBERS` | `8`; subscribers per stream |
| `MAX_DATASETS` / `MAX_MODELS` | `50` each; oldest registry entries evicted |
| `RATE_LIMIT_PER_MINUTE` | `60`; POSTs per peer in rolling 60 s |
| `RATE_LIMIT_GLOBAL_PER_MINUTE` | `180`; POSTs per process in rolling 60 s |
| `MAX_BODY_BYTES` | `262144`; POST body limit |
| `TRUSTED_PROXY_IPS` | `127.0.0.1`; trusted forwarded headers; do not use `*` publicly |

Use positive values for stream settings and sensible positive capacities/limits. Memory caps, body timeout, request shapes and max tokens are code constants, not extra environment settings. `CACHE_BACKEND`, `STORE_BACKEND`, and `REDIS_URL` appear only in legacy test-fixture setup, not runtime configuration.

Deployment invariant: **one worker / one replica**. PostgreSQL snapshots are for a bounded single-writer demo; stream buffers and rate limits never become durable. Local persistence tests use database doubles. No live database, collector or paid deployment was contacted during this verification.
