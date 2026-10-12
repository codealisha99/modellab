# ModelLab

<img src="app/static/icon.svg" width="48" height="48" alt="ModelLab checkpoint logo" />

A developer lab for simulated model training, ranked three-tier memory, and verifiable resumable token streams. Built with FastAPI and vanilla HTML/CSS/JavaScript. **No external API keys, database, or GPU are needed locally.** Training and tokens are simulations; tenant IDs are namespaces, not authentication.

Created and maintained by [Alisha Karma](https://alishakarma.com) ([codealisha99](https://github.com/codealisha99)); contact [lishykarma99@gmail.com](mailto:lishykarma99@gmail.com). Historical authorship and third-party notices remain intact.

## Quick start

Use Python 3.13 (the Docker/CI version); local verification used Python 3.14.4. Commands below use a POSIX shell.

```bash
git clone https://github.com/codealisha99/modellab.git
cd modellab
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
# Ensure this demo uses local memory, not an inherited database configuration.
unset DATABASE_URL DATABASE_URL_UNPOOLED OTEL_EXPORTER_OTLP_ENDPOINT
OTEL_SDK_DISABLED=true python -m app.run
```

Already have a checkout? Skip cloning and start from its root. On Windows, activate with `.venv\Scripts\Activate.ps1` and set/unset environment variables in PowerShell instead. `.env.example` is a reference: **the application does not automatically load `.env`.**

Open [the workspace](http://localhost:8005/playground), [overview](http://localhost:8005/), [interactive docs](http://localhost:8005/docs), or [API reference](http://localhost:8005/redoc). Run one worker and one replica; stream state is in process memory.

## Verify

In another terminal, from the repository root:

```bash
source .venv/bin/activate
unset DATABASE_URL DATABASE_URL_UNPOOLED OTEL_EXPORTER_OTLP_ENDPOINT
python -m pytest -q
python -m pip check
python3 scripts/build_frontend.py
# Optional local check; CI also runs it. Requires Node.js.
for file in app/static/*.js; do node --check "$file"; done
curl -fsS http://localhost:8005/health
```

The build regenerates ignored `public/`; it does not publish. Verification on 2026-10-12: 153 tests passed, 90.19% coverage; local HTTP demo passed. See the demo guide for verification limits.

## Guides

- [Project guide](docs/PROJECT_GUIDE.md): architecture, feature behavior, and implementation status.
- [Demo guide](docs/DEMO_GUIDE.md): startup, presentation steps, pitch, and recovery.
- [API dependencies](docs/API_DEPENDENCIES.md): integrations, credentials, environment variables, and deployment configuration.

Maintenance: [contributing](CONTRIBUTING.md), [design system](DESIGN_SYSTEM.md), and [third-party notices](THIRD_PARTY_NOTICES.md). No project-wide LICENSE file has been selected.
