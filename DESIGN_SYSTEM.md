# ModelLab design system

ModelLab is a practical developer lab for simulated training, tenant memory, and resumable token streams. The visual direction is a restrained technical workspace: readable light surfaces, teal actions, slate text, and dark instrument panels. The landing diagram explains replay rather than decorating the page. Alisha Karma is credited as creator and maintainer in the shared footer; the product keeps its own name.

## Semantic palette

| Role | HEX |
|---|---|
| Brand / hover / active | `#087C75` / `#086760` / `#06534D` |
| Selected surface | `#E1F2EF` |
| Page / surface / muted surface | `#F2F6F5` / `#FFFFFF` / `#EAF0EF` |
| Primary / secondary / muted text | `#1C3034` / `#4A6266` / `#586E72` |
| Divider / input border | `#D6E2DF` / `#7B9290` |
| Success / warning / error / info | `#176B53` / `#85530B` / `#A32928` / `#345BA4` |
| Terminal background / text / muted | `#183237` / `#E0EEEC` / `#ABC2C1` |
| Terminal success / warning / error | `#ACE5D4` / `#FFDC9B` / `#FFBFB7` |

All tokens, including state backgrounds, disabled colors, focus, and motion, are in `app/static/tokens.css`. Use semantic variables in component styles. Light surfaces and dark output panels belong to one theme; there is no unsupported theme switch.

Measured principal contrast ratios: primary text on white 13.80:1; muted text on page 4.96:1; white on brand 5.06:1; brand links on page 4.64:1; terminal text 11.36:1; terminal muted text 7.24:1; input borders on white 3.30:1. These are computed using the WCAG relative luminance formula, not a certification of every vendor-rendered state.

## Type, spacing, and controls

Manrope is the locally served variable UI font; JetBrains Mono is used for tokens, identifiers, and code. Both use `font-display: swap` and system fallbacks. The type scale is 12, 14, 16, 18, and 24 px, with fluid page headings of 28–36 px and display headings of 34–56 px. Body line-height is 1.65; display line-height is 1.12.

Spacing follows 4, 8, 12, 16, 20, 24, 32, 40, 48, and 64 px. Main content is capped at 1200 px with fluid gutters. Controls have a 44 px minimum height, 8 px corners, and explicit disabled, focus, hover, error, and busy states. Panels use 12 px corners. Animation lasts 140 ms; reduced motion disables transitions, cursors, and spinners.

The practical shared system includes the header, active navigation, skip link, footer, buttons, form fields, panels, status pills, alerts, statistics rows, output, model results, and event log. These use shared CSS rather than a new component framework. Layout changes at 1000, 800, and 600 px; the narrow navigation stays visible as a two-column grid without a hidden menu.

## Rendering and maintenance

### Logo and wordmark

The ModelLab checkpoint mark uses three connected squares, reflecting the three checkpoints created by a sample training run and the ordered events in a replayable stream. It is original vector artwork, rendered in the existing brand teal `#087C75` with white checkpoints. Keep the ModelLab wordmark separate from creator attribution.

`app/static/icon.svg` is the single source for the header, footer, browser favicon, and README. Use explicit dimensions to prevent layout shifts. Header and footer images have empty alternative text because adjacent text already names the product; the README image has a descriptive label. Do not duplicate the SVG geometry in templates. Keep the mark readable at favicon size and leave clear space around it.

`app/frontend.py` renders the shared shell for `/`, `/playground`, `/docs`, and `/redoc`. `scripts/build_frontend.py` uses the same renderer for Vercel. The playground remains usable on both application routes.

Swagger UI 5.33.1 and ReDoc 2.5.4 remain third-party documentation renderers. `docs.js` wraps Swagger summary components to preserve expansion and standalone permalinks without nested interactive elements. ReDoc reads the semantic tokens through `reference.js`. Pin versions and retest documentation interactions before upgrading: [Swagger's plugin guidance](https://swagger.io/docs/open-source-tools/swagger-ui/customization/plugin-api/) treats internal component interfaces as version-sensitive.

The workspace includes anchor navigation between streams, model evaluation, and memory retrieval. Memory controls use existing field and button tokens, a status message, and plain scored result rows. Both documentation pages share a request guidance panel. HTML 404 responses use the same shell; API 404s remain JSON.

ReDoc uses the darker active brand token because its constraint labels apply transparency. Swagger execution, cancel, download, response, and code-sample states use semantic tokens too. cURL samples become labelled keyboard-focusable regions after rendering. Documentation CSP permits ReDoc’s blob worker only on documentation routes. Theme customization follows [ReDoc CE configuration](https://github.com/Redocly/redoc/blob/main/docs/config.md).
