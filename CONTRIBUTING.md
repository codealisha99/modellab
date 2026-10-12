# Contributing to ModelLab

ModelLab is created and maintained by [Alisha Karma](https://alishakarma.com) ([codealisha99](https://github.com/codealisha99)). Git history records individual contributions; this attribution does not replace them.

For maintainer inquiries, contact [lishykarma99@gmail.com](mailto:lishykarma99@gmail.com). Code ownership is defined in [.github/CODEOWNERS](.github/CODEOWNERS); dependency and font credits are listed in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

Use Python 3.12–3.14 and install `requirements-dev.txt` in a virtual environment. Run `pytest`, `python3 scripts/build_frontend.py`, and `node --check` on modified JavaScript. Keep the 70% coverage gate. Check every affected page at desktop, tablet, and mobile widths, including keyboard and error states.

The verification workflow runs these checks on pushes and pull requests to `main` using Python 3.13 and Node.js 24. Actions are pinned to commit SHAs. Remote CI results are available only after the workflow is committed and pushed.

Keep training and token simulation explicit. Preserve tenant isolation, API contracts, bounded stores, and streaming replay semantics. Never commit credentials or change production data for tests. Frontend tokens and conventions are in [DESIGN_SYSTEM.md](DESIGN_SYSTEM.md).

Open a focused change with the problem, resulting behavior, and checks actually executed. The maintainer reviews changes before release. This repository has no project-wide LICENSE file. Keep all font notices and third-party credits; the maintainer must choose any future project license.
