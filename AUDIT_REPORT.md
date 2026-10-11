# ModelLab product, ownership, and production audit

Date: 2026-10-11. Status: completed locally with verification limits. The implementation audit performed no commit, push, manual deployment, remote URL change, permission change, Git identity change, or production data mutation. The user subsequently authorized committing and pushing these changes; the configured main-branch integrations may deploy that push. The previous report is preserved in [the historical audit](docs/audits/previous-redesign.md); its release authorization does not apply to this session.

## A. Verified product identity and discovery

ModelLab is a developer lab for deterministic CPU mock training, scored three-tier memory, and verifiable resumable simulated streams. Its users are developers exploring dataset/train/evaluate behavior, memory retrieval, and SSE replay. It is not a GPU training or authenticated private-memory service. The design direction is a restrained technical laboratory: muted teal actions, slate surfaces, dark output instruments, and an explanatory event-replay diagram.

Creator and intended primary maintainer: Alisha Karma, `codealisha99`. Website, GitHub, X, and contact match the supplied identity. Attribution describes the product’s creator and maintainer, not sole authorship of every line.

Inspected all tracked source, templates, styles, frontend scripts, API routes, training/memory/stream stores, optional PostgreSQL snapshot persistence, guards, tracing, dependencies, tests, Docker/Railway/Vercel configuration, fonts, notices, package metadata, README, PRD, and prior verification documents. Stack: Python/FastAPI/Pydantic/Uvicorn, vanilla HTML/CSS/JS, pytest; npm is a command wrapper, not a JS dependency tree. Four existing user-facing routes; no auth, account, billing, dashboard, legal, or CRUD page set. `/docs/oauth2-redirect` is a vendor callback helper, not a product page.

Started from a clean `main` at `578a2d5`; origin already points to `https://github.com/codealisha99/modellab.git`. Read-only `gh repo view` confirmed a public repository with empty description/topics. No repository-level CI, lint, or static-type configuration exists. The Git identity was inspected and left unchanged; an existing email is not assumed verified.

## B. Design system

Central tokens in `app/static/tokens.css`: brand `#087C75`, hover `#086760`, active `#06534D`, selected `#E1F2EF`; page `#F2F6F5`, surface `#FFFFFF`, muted `#EAF0EF`; text `#1C3034`, secondary `#4A6266`, muted `#586E72`; borders `#D6E2DF` / `#7B9290`; success `#176B53`, warning `#85530B`, error `#A32928`, info/secondary `#345BA4`; terminal `#183237` with text `#E0EEEC`. Focus, disabled, state backgrounds, motion, and radii remain centralized.

Locally hosted Manrope for UI and JetBrains Mono for code, both with swap/fallback loading. Type: 12/14/16/18/24 px; page headings 28–36 px, display 34–56 px. Spacing: 4/8/12/16/20/24/32/40/48/64 px; 1200 px content, fluid gutters, 24 px grid gap, 44 px controls, 8 px control/12 px panel corners, 140 ms transitions. Reduced motion is preserved. Reference content can expand to 1472 px for its three-column renderer.

Shared header, four-item active navigation, visible two-column mobile navigation, footer, metadata, favicon, panels, forms, buttons, alerts, output, statistics, and empty/loading/error states updated. Added memory results, documentation request guidance, and a shared-shell HTML 404. Principal contrast pairs were calculated: white/brand 5.06:1; brand/page 4.64:1; primary text/white 13.80:1; muted/page 4.96:1; terminal text 11.36:1; input border/white 3.30:1. See [DESIGN_SYSTEM.md](DESIGN_SYSTEM.md).

## C. Route inventory and completion

All four existing routes were inspected before implementation. Problems and changes: overview copy overstated persistence; workspace did not expose memory; docs lacked practical request guidance; reference shared the docs active link; unknown URLs exposed JSON to browsers. Common changes apply the new system to each route.

| Route | Purpose | Design updated | Functionality tested | Responsive check | Status |
|---|---|---|---|---|---|
| `/` | Overview and embedded experiments | Yes: copy, replay visual, shared system, memory | Navigation, keyboard skip, real six-token stream, shared forms | 320/390/768/1024/1440/1600 px | Verified locally |
| `/playground` | Stream, model, and memory workspace | Yes: anchor navigation, panels, memory controls | Replay/checksum, cancellation, training, save/search, filtering, errors | Same six widths | Verified locally |
| `/docs` | Interactive Swagger API documentation | Yes: guidance, controls, samples, shell | Expand, Try it out, actual `/health` 200, permalink | Same six widths; executed state at 390/1440 | Verified locally |
| `/redoc` | Read-only API reference | Yes: guidance, active route, theme/constraint contrast | Schema rendering, memory search, and navigation | Same six widths | Verified locally |
| Unmatched page URL; tested `/unknown-page` | 404 recovery state | Added shared shell | 404 HTTP status, recovery links; API errors stay JSON | Same six widths | Verified locally |

Every listed route progressed through inspection, implementation, functional checks, responsive checks, and local verification. No route requires authentication. Model and memory mutations used local sample data only. API routes, `/health`, `/openapi.json`, and the OAuth callback were checked separately and are not counted as product pages.

New memory controls call the existing save and ranked-search endpoints. Each tab starts with a random tenant namespace; storage restriction is tolerated. Copy explains namespace IDs do not authenticate users. Validated real save/search, empty tier, separation between tenants, safe literal rendering of HTML-like text, failure recovery, and dropping stale responses after tenant changes. No schema, persistence mechanism, API payload, or backend business workflow was replaced.

## D. Ownership and originality

Corrected the private npm name from the unrelated `@ai-infra` namespace to `modellab`; added creator/repository metadata. Updated footer, author/social metadata, README, maintainer documentation, and `.github/CODEOWNERS` to the canonical identity. Added a secret-free `.env.example` that explicitly does not promise automatic dotenv loading. Module descriptions now say ModelLab; README preserves the original TuneLab/MemOS requirement lineage. No fake metrics, customers, testimonials, new legal pages, or ownership history were introduced.

Manrope/JetBrains Mono SIL notices, Swagger/ReDoc branding, intentional service URLs, and historical commits remain. Renderer license types were verified from pinned package metadata. Current production availability, connected account configuration, database credentials, and GitHub email verification were not inferred from older documents. Remote description/topics remain empty and unchanged.

## E. Code quality and security

Important changes: shared renderer/templates, semantic tokens/styles, `memory.js`, docs/reference scripts, request guard, HTML 404 handler, package/static build, frontend/hardening tests, and ownership/docs. Added three meaningful regressions: browser/API 404 negotiation, shared static 404 packaging, and security headers on guard rejections. No dependencies added or removed.

Found and fixed guard early returns omitting security headers. Rate limit, body-size, timeout, and nesting rejections now use the same header wrapper. Documentation alone permits ReDoc’s blob worker; app CSP remains self-only. Frontend API calls time out after 15 seconds, and the stream shortcut is scoped to its form. Result strings use text nodes. Existing bounded stores, request validation, database rollback, single-worker policy, and simulated-output disclosure remain.

No blind global identity/comment removal was used. Removed obsolete module-name descriptions and safely corrected CSS selector collisions introduced during implementation. Retained comments about replay, storage restrictions, security, and vendor adaptation. Existing font and vendor dependencies remain intentional. A tracked-text credential-pattern scan found no matching token/private-key/database-credential patterns; this is not a full secret-history or dependency-vulnerability audit.

## F. Executed verification and evidence

- Baseline: `.venv/bin/python -m pytest -q`, 150 passed, 90.10% coverage. Production/static build, pip check, and all original JS syntax checks passed.
- After Python/security changes: 153 tests passed, 90.19% coverage; unchanged 70% gate. Existing training, streaming store/HTTP/live-socket, hardening, and mocked persistence tests passed. No tests were disabled.
- `python3 scripts/build_frontend.py`: passed; landing/workspace/404 use shared renderer; current local assets copied; audit-only axe script removed before final packaging.
- `.venv/bin/python -m pip check`: no broken requirements.
- `node --check app/static/{app,memory,docs,reference}.js`: each executed and passed.
- `git diff --check`: passed; source and metadata diff reviewed.
- Browser: T3 preview was intermittent, so local gstack browse captured and measured initial layouts. T3 returned and performed final interactions, all-route/six-width checks, and final saved screenshots. No final page-level overflow. Desktop/mobile screenshots inspected; 320 px nav overflow and a gutter selector regression were caught and fixed before final checks.
- Real local stream: 60 tokens across one resume, contiguous IDs, SHA-256 matches. Cancellation, training/evaluation (three checkpoints, honest zero held-out improvement), clear log, form invalid focus, memory save/search/filter/separation, stale-response discard, and injected network-error recovery passed. Swagger executed `/health` and returned 200 with ModelLab JSON. Keyboard Tab reached the skip link with a visible outline; Enter navigated to the playground. The overview separately completed a six-token stream with a matching SHA-256 checksum. ReDoc search returned memory operations.
- Axe-core 4.10.3, WCAG A/AA tags including 2.1/2.2: final landing/workspace/404 scans and corrected docs/reference scans at 390/1440 reported zero violations. Expanded Swagger request/response state was also scanned after fixing execution/cancel/download/sample contrast and mobile cURL keyboard access. ReDoc transparent constraint labels were fixed using a darker semantic brand token. Axe still marks color-contrast/vendor `aria-prohibited-attr` nodes for manual review; zero automated violations is not full certification.
- Read-only `gh repo view` confirmed owner/public status/empty metadata. `docker info` failed because the local Docker daemon socket is unavailable; container build was not run.

Baseline warning remains: Starlette deprecates its httpx TestClient integration. Earlier deployment statements are archived historical claims, not checks executed in this audit. Docker, physical devices, Firefox/Safari, screen-reader certification, live PostgreSQL, and production deployment health were not verified. There is no configured lint/type/E2E runner to claim as passed.

## G. Genuine remaining work

1. Manually review vendor ARIA/contrast nodes and test Safari, Firefox, and assistive technology.
2. Start Docker to verify the container; separately verify the existing production database/deployment with authorized access. Local persistence tests mock database behavior.
3. Consider adding an accurate GitHub description/topics and CI in a separate repository-maintenance change. No remote metadata was modified here.
4. Resolve the existing Starlette/httpx migration in a focused dependency change. No project-wide LICENSE file exists; selecting one is a maintainer decision, separate from the preserved third-party notices.
5. Install Vercel CLI (`npm i -g vercel`) for future platform diagnostics such as env pull, logs, and deployment inspection. No install or deployment was required for this static/local audit.

Existing product limits remain explicit: mock CPU training, simulated tokens, hash-based embeddings, public namespaces without authentication, bounded single-writer snapshots, and transient streams. Commit and push were subsequently authorized by the user. Manual deployment, repository permissions, DNS, and production data changes remain outside this release action. The implementation is recorded in the release commit.
