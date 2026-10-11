# ModelLab redesign and production audit

Date: 2026-10-11. The redesign was verified locally before release. The user subsequently authorized committing, pushing, production deployment, and updating the Vercel CLI.

## A. Product and branding

ModelLab remains a developer lab for CPU mock training, tenant memory, and resumable simulated streams. The redesign uses a restrained light developer workspace with blue actions and navy output panels. Creator attribution links to Alisha Karma's website, GitHub, and X in the footer; personal contact details are not presented as product support.

Local Manrope and JetBrains Mono fonts remain in use. Colors, type, spacing, state colors, corner radii, control sizing, focus, and motion are centralized in `tokens.css`. See `DESIGN_SYSTEM.md` for the complete palette and principal contrast measurements.

## B. Routes and components

Audited `/`, `/playground`, `/docs`, `/redoc`, plus `/docs/oauth2-redirect`, `/openapi.json`, `/health`, and linked static assets. There are no login, signup, dashboard, settings, legal, or other application pages in this repository.

Shared templates provide consistent navigation, active routes, skip links, titles, footer, and creator attribution. The landing page retains its working playground; the dedicated workspace focuses on controls and output. Health is visible on both routes. Documentation now shares the product shell and fonts, with valid Vercel rewrites for the reference and OAuth helper.

Improved labels and helper text, invalid-field focus, button busy states, service failure recovery, storage restrictions, restore races, checksum fallback messaging, result focus, restrained announcements, and event-log empty states. All app controls have 44 px minimum height; responsive layouts stack panels and wrap long event text. Reduced-motion preferences are honored. Swagger summary links are separated from disclosure buttons; code samples retain readable dark backgrounds.

## C. Cleanup and architecture

Replaced duplicated HTML string substitutions with one stdlib template renderer used by FastAPI and the static build. Moved page markup from `app/static/index.html` to `app/templates/playground.html`. Consolidated duplicate and conflicting CSS and centralized semantic tokens. Removed unused timer bookkeeping and decorative separator comments from the frontend; retained comments explaining stream deduplication, replay, storage restrictions, cryptography fallback, and the Swagger accessibility adaptation. Backend validation, security, persistence, tracing, and licensing documentation remain intact.

No framework, schema, business logic, API payload, authentication, or persistence integration was replaced. No package dependencies were added. Existing documentation CDN versions are now pinned. The documentation-only CSP allows ReDoc's attribution image and Swagger asset preloads; application pages retain the strict self-only policy.

## D. Verification

Executed:

- `.venv/bin/python -m pytest -q`: **150 passed**, **90.10% coverage**, above the unchanged 70% gate. Includes existing streaming, hardening, persistence, training, and memory tests and eight new public-page/packaging regressions.
- `node --check` for `app.js`, `docs.js`, and `reference.js`: passed.
- `.venv/bin/python -m pip check`: no broken requirements.
- `python3 scripts/build_frontend.py`: passed; generated landing and workspace match the shared renderer and copy current assets.
- `git diff --check`: passed.
- TestClient checks: all public pages, local assets, linked internal routes, schema, health, and OAuth helper return 200. UI routes remain excluded from the API schema.

The first isolated frontend test run exposed a missing explicit checkbox association; the existing wrapping label was valid, and an explicit `for` was added for clarity. That isolated run also fell below the suite-wide coverage gate; the subsequent complete suite passed without changing coverage settings.

T3 browser checks covered all four UI routes at 320, 390, 768, 1024, 1440, and 1600 px. No page-level horizontal overflow was measured. Desktop and mobile screenshots were visually inspected. Tested actual stream completion, a disconnect at event 5 followed by replay and a matching SHA-256 checksum across 60 tokens, cancellation, sample training/evaluation, result focus, and clearing the log. Empty-prompt validation focused and marked the field. An injected rejected browser fetch verified failure recovery and restored Start availability; success checks used real local endpoints. Swagger Try it out executed `/health` with a 200 response; operation expansion and hash links remained functional.

Axe-core 4.10.3 scans using WCAG A/AA tags reported **zero violations** on the final landing, playground, ReDoc, and expanded Swagger health operation. Scans included narrow layouts and result states. Automated checks left manual-review items: overlapping/non-text contrast nodes in application forms, vendor copy-button wrapper ARIA in Swagger, and renderer-dependent contrast nodes in ReDoc. Principal application color pairs were measured separately. Temporary axe assets were removed from source and generated output. These results do not constitute full screen-reader or WCAG certification.

## E. Important files

- Added: `app/frontend.py`, `app/templates/{layout,header,footer,playground}.html`, `app/static/{tokens.css,docs.js,reference.js}`, `tests/test_frontend.py`, `DESIGN_SYSTEM.md`, this report.
- Updated: `app/api/main.py`, `app/api/guard.py`, `app/static/{style.css,app.js,icon.svg}`, `scripts/build_frontend.py`, `vercel.json`, `README.md`.
- Removed: superseded `app/static/index.html`.
- No new package dependencies or retained audit-only scripts.

## F. Remaining work and limits

- Release was authorized after the local audit. Production deployment and public-route checks are performed after the release commit; platform deployment records identify the running revision.
- No repository lint or static type-check configuration exists; syntax, tests, packaging, and dependency checks were run instead.
- Existing Starlette emits an httpx deprecation warning. It does not fail the suite; a dependency migration was kept outside this visual audit.
- Safari, Firefox, physical devices, and a full manual screen-reader audit were not exercised. Third-party documentation manual-review items above remain verification limits.
- Documentation still needs its existing CDN connection. Streams remain transient, single-process, and lost on restart; training remains a CPU simulation. These are existing product limits, not redesign regressions.
- Vercel CLI was upgraded from 51.8.0 to 63.1.2 using `npm i -g vercel@latest`; project inspection succeeded. npm reported a transitive package engine warning under local Node 25.6.1; Vercel production uses Node 24.x.
