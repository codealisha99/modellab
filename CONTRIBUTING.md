# Contributing to ModelLab

ModelLab is created and maintained by [Alisha Karma](https://alishakarma.com) ([codealisha99](https://github.com/codealisha99)). Git history records individual contributions; this attribution does not replace them.

Use Python 3.12–3.14 and install `requirements-dev.txt` in a virtual environment. Run `pytest`, `python3 scripts/build_frontend.py`, and `node --check` on modified JavaScript. Keep the 70% coverage gate. Check every affected page at desktop, tablet, and mobile widths, including keyboard and error states.

Keep training and token simulation explicit. Preserve tenant isolation, API contracts, bounded stores, and streaming replay semantics. Never commit credentials or change production data for tests. Frontend tokens and conventions are in [DESIGN_SYSTEM.md](DESIGN_SYSTEM.md).

Open a focused change with the problem, resulting behavior, and checks actually executed. The maintainer reviews changes before release. This repository has no project-wide LICENSE file. Keep all font notices and third-party credits; the maintainer must choose any future project license.
