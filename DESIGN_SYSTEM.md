# ModelLab design system

ModelLab is a practical developer lab for simulated training, tenant memory, and resumable token streams. The visual direction is a restrained technical workspace: readable light surfaces, blue actions, and navy output panels. The landing diagram explains replay rather than decorating the page. Alisha Karma is credited as creator in the shared footer; the product keeps its own name.

## Semantic palette

| Role | HEX |
|---|---|
| Brand / hover / active | `#2855D9` / `#2044B1` / `#19378F` |
| Selected surface | `#EAF0FF` |
| Page / surface / muted surface | `#F4F7FB` / `#FFFFFF` / `#EDF1F7` |
| Primary / secondary / muted text | `#182438` / `#526075` / `#606C80` |
| Divider / input border | `#DCE3ED` / `#7C899E` |
| Success / warning / error / info | `#176B53` / `#85530B` / `#A32928` / `#2855B5` |
| Terminal background / text / muted | `#192338` / `#DCE4F5` / `#A6B3CD` |
| Terminal success / warning / error | `#A4EED9` / `#FFDC9B` / `#FFBFB7` |

All tokens, including state backgrounds, disabled colors, focus, and motion, are in `app/static/tokens.css`. Use semantic variables in component styles. Light surfaces and dark output panels belong to one theme; there is no unsupported theme switch.

Measured contrast ratios: primary text on white 15.58:1; muted text on page 4.94:1; white on brand 6.19:1; terminal text 12.29:1; terminal muted text 7.43:1; input borders on white 3.54:1. These cover the principal pairs against [WCAG contrast requirements](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html); they are not a certification of every vendor-rendered state.

## Type, spacing, and controls

Manrope is the locally served variable UI font; JetBrains Mono is used for tokens, identifiers, and code. Both use `font-display: swap` and system fallbacks. The type scale is 12, 14, 16, 18, and 24 px, with fluid page headings of 28–36 px and display headings of 34–56 px. Body line-height is 1.65; display line-height is 1.12.

Spacing follows 4, 8, 12, 16, 20, 24, 32, 40, 48, and 64 px. Main content is capped at 1200 px with fluid gutters. Controls have a 44 px minimum height, 8 px corners, and explicit disabled, focus, hover, error, and busy states. Panels use 12 px corners. Animation lasts 140 ms; reduced motion disables transitions, cursors, and spinners.

The practical shared system includes the header, active navigation, skip link, footer, buttons, form fields, panels, status pills, alerts, statistics rows, output, model results, and event log. These use shared CSS rather than a new component framework. Layout changes at 1000, 800, and 600 px; the narrow navigation stays visible without a hidden menu.

## Rendering and maintenance

`app/frontend.py` renders the shared shell for `/`, `/playground`, `/docs`, and `/redoc`. `scripts/build_frontend.py` uses the same renderer for Vercel. The playground remains usable on both application routes.

Swagger UI 5.33.1 and ReDoc 2.5.4 remain third-party documentation renderers. `docs.js` wraps Swagger summary components to preserve expansion and standalone permalinks without nested interactive elements. ReDoc reads the semantic tokens through `reference.js`. Pin versions and retest documentation interactions before upgrading: [Swagger's plugin guidance](https://swagger.io/docs/open-source-tools/swagger-ui/customization/plugin-api/) treats internal component interfaces as version-sensitive.
