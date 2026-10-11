"""One HTML shell for FastAPI pages and the Vercel static build."""
from html import escape
from pathlib import Path
from string import Template

TEMPLATES = Path(__file__).resolve().parent / "templates"


def render_page(page="landing", *, content=None, extra_head="", scripts=""):
    titles = {
        "landing": "ModelLab · Models, memory, and reliable streams",
        "workspace": "ModelLab · Experiment workspace",
        "docs": "ModelLab · Interactive API docs",
        "redoc": "ModelLab · API reference",
        "not-found": "ModelLab · Page not found",
    }
    if page not in titles:
        raise ValueError("Unknown frontend page")
    is_playground = page in ("landing", "workspace")
    if is_playground:
        content = (TEMPLATES / "playground.html").read_text()
        scripts = '<script src="/static/app.js" defer></script><script src="/static/memory.js" defer></script>'
    if page == "not-found":
        content = (TEMPLATES / "not-found.html").read_text()
    header = Template((TEMPLATES / "header.html").read_text()).substitute(
        overview_current='aria-current="page"' if page == "landing" else "",
        playground_current='aria-current="page"' if page == "workspace" else "",
        docs_current='aria-current="page"' if page == "docs" else "",
        reference_current='aria-current="page"' if page == "redoc" else "",
    )
    return Template((TEMPLATES / "layout.html").read_text()).substitute(
        title=escape(titles[page]),
        description="Explore sample model training, tenant memory, and verifiable resumable token streams. Training and tokens are simulated.",
        page_class=page,
        extra_head=extra_head,
        scripts=scripts,
        header=header,
        footer=(TEMPLATES / "footer.html").read_text(),
        content=content or "",
        skip_target="playground" if is_playground else "main-content" if page == "not-found" else "api-reference",
        skip_label="the playground" if is_playground else "page content" if page == "not-found" else "the API reference",
    )
