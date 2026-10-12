# Ownership, contributor, and branding audit

Date: 2026-10-12. Scope: current repository at `f6179d2`, legitimate authorship and contribution metadata, documentation hygiene, CI, and logo consistency. The working tree was clean at the start. The audit initially left reviewable changes uncommitted and did not push, deploy, rewrite history, change remotes, or change remote settings. The user subsequently authorized committing and pushing this audit; that push can trigger CI and the existing connected deployment integrations.

## Canonical identity

- Primary author and maintainer: Alisha Karma, GitHub `codealisha99`.
- GitHub: https://github.com/codealisha99
- Website: https://alishakarma.com
- Public maintainer contact: lishykarma99@gmail.com

ModelLab remains the product name. Attribution identifies its creator and primary maintainer; it does not assert exclusive authorship of dependencies, fonts, or every line of source.

## Repository and metadata inspected

Reviewed branch, remotes, working tree, recent commits, complete contributor summary, Git configuration, README, CONTRIBUTING, CODEOWNERS, package.json, environment instructions, third-party/font notices, design system, PRD, existing dated audit/verification documents, templates/assets/page metadata, tests, requirements, Docker, Railway, and Vercel configuration. No project-wide LICENSE, pyproject.toml, Cargo.toml, pom.xml, changelog, or release-note file exists. The npm manifest is a private command wrapper; Python requirements are the actual dependency manifests.

Read-only authenticated GitHub checks confirmed:

| Setting | Observed value |
| --- | --- |
| Repository | `codealisha99/modellab` |
| Owner and authenticated account | `codealisha99` |
| Visibility | Public |
| Default branch | `main` |
| Repository description | Empty |
| Topics | Empty |
| Default branch protected | No |
| Collaborators | `codealisha99`, admin |
| GitHub contributor list | `codealisha99`, 11 commits |
| GitHub license metadata | None |

`git shortlog -sne HEAD` also reports one recorded identity across 11 commits. This is a summary of recorded authorship, not proof of sole original authorship. No contributor records were removed or altered. The `private: true` npm flag controls publication and is not inconsistent with a public GitHub repository.

## Corrections implemented

| File | Change and reason |
| --- | --- |
| `package.json` | Added the supplied public email to the existing Alisha Karma author record; preserved ModelLab, private publication status, and repository URL. |
| `README.md` | Added the actual logo, portable clone/setup steps, verification commands, source-architecture table, CI link, ownership/licensing clarification, and this audit link. Removed absent monorepo/Compose assumptions and clarified that the sample YAML is not automatically loaded. |
| `CONTRIBUTING.md` | Added canonical maintainer contact, ownership/notice links, and accurate CI instructions. Preserved contribution history and project-license limitation. |
| `.github/workflows/verify.yml` | Added verification for pushes/PRs to `main`: Python 3.13, Node 24, dependency consistency, existing pytest coverage gate, JS syntax, and static build. Official actions pinned to verified commit SHAs, read-only contents permission, checkout credentials not persisted. No deployment or privileged pull-request trigger. |
| `app/static/icon.svg` | Replaced the generic M tile with an original three-checkpoint vector mark using the established teal/white palette. |
| `app/templates/header.html` | References the actual logo asset instead of duplicating SVG artwork. Product home accessible name remains intact. |
| `app/templates/footer.html` | Uses the same mark beside the ModelLab wordmark; existing canonical creator links remain. |
| `app/static/style.css` | Aligns footer mark and wordmark with existing spacing tokens. |
| `DESIGN_SYSTEM.md` | Documents logo meaning, shared source, clear space, dimensions, and accessible usage. |
| This file | Records actual findings, modifications, checks, and limitations. |

The mark’s three connected squares reference sample-training checkpoints and stable ordered streaming events. The existing teal palette and locally hosted typography stay intact. Header, footer, browser favicon, README, FastAPI pages, and static build use the same artwork. Header/footer images are decorative beside product text; README uses descriptive alternative text. No unrelated trademark, stock image, or fictional organization was introduced.

## Preserved attribution and history

CODEOWNERS already correctly names `@codealisha99` and needed no change. Application author metadata and existing footer links were already canonical. Manrope and JetBrains Mono copyright/OFL files, Swagger UI and ReDoc notices, service integrations, and source explanations remain intact. Historical verification and release reports remain dated historical evidence rather than being edited to suggest new checks. Original TuneLab/MemOS lineage references are intentional history; Alice/Bob/Acme strings in tests are fixtures, not contributor identities.

No dependency, application workflow, database schema, secret value, font license, or Git commit was replaced. A tracked-text credential-pattern scan found no matches; this does not constitute a complete secret-history or vulnerability audit.

## Future Git identity

The authenticated GitHub login and account ID match the existing public noreply address already configured in this repository. No address was guessed. GitHub email-settings access failed, so verification through account settings remains unknown. The existing email was retained unchanged. Repository-local `user.name` is now **Alisha Karma**, as requested for future commits under this identity. Global Git settings, historical authors, branches, and remotes were not modified.

## Checks actually executed

- Baseline full suite: 153 passed, 90.19% coverage.
- Final full suite after template/logo/metadata changes: 153 passed, 90.19% coverage, unchanged 70% gate.
- `python3 scripts/build_frontend.py`: passed; current assets and shared pages packaged.
- `.venv/bin/python -m pip check`: no broken requirements.
- `node --check` on every `app/static/*.js`: passed.
- Ruby YAML parser on `.github/workflows/verify.yml`: syntax valid. A Python YAML parser and actionlint are not installed; no dependency was added merely for this audit.
- Action release versions and commit pins resolved from official GitHub repositories through the authenticated API.
- `git diff --check`: passed; final diff reviewed.
- T3 browser evaluation confirmed loaded header/footer logo assets, correct favicon path, ModelLab title, and Alisha Karma author metadata. Overview checked at 320/390/768/1440 px with no page overflow; workspace checked at 320/390/768 px with no page overflow. Further route/viewport inspection and screenshots were interrupted by preview disconnections/timeouts. The suite separately verified all four pages and their linked local assets. No new screenshot or complete cross-browser certification is claimed.

At audit completion, the new workflow had not run on GitHub because the changes had not yet been committed or pushed. Subsequent commit/push authorization enables the first hosted run; its outcome is not established by the local audit. YAML validation and executing its commands locally do not establish hosted-runner success. No configured linter or Python static-type checker exists. The existing Starlette/httpx TestClient deprecation warning remains non-failing.

## Remaining decisions and limits

- Add a GitHub description/topics only with a separate settings decision. Suggested description: “Developer lab for simulated model training, ranked memory retrieval, and resumable SSE streams.” Suggested topics: `fastapi`, `python`, `server-sent-events`, `developer-tools`, `model-evaluation`.
- Choose any project-wide license explicitly; no license or copyright ownership assertion was invented.
- Decide on branch protection separately; the audit does not change permissions or protections.
- GitHub email-settings verification remains inaccessible. Existing public noreply is account-matched and unchanged.
- Verify the CI job on the hosted runner after an authorized commit/push. Capture final logo screenshots when the collaborative preview is stable; desktop/mobile layout evaluation is partial as recorded above.

Historical Git authorship and third-party notices are preserved. There was no unrelated uncommitted work at the start, and only the listed audit/branding corrections and repository-local Git display-name setting were made.
