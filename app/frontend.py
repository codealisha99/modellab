"""One HTML shell for FastAPI pages and the Vercel static build."""
from html import escape
from pathlib import Path
from string import Template

TEMPLATES = Path(__file__).resolve().parent / "templates"


def render_page(page="landing", *, content=None, extra_head="", scripts=""):
    titles = {
        "landing": "ModelLab · Models, memory, and reliable streams",
        "workspace": "ModelLab · Streaming playground",
        "docs": "ModelLab · Interactive API docs",
        "redoc": "ModelLab · API reference",
    }
    if page not in titles:
        raise ValueError("Unknown frontend page")
    is_playground = page in ("landing", "workspace")
    if is_playground:
        content = (TEMPLATES / "playground.html").read_text()
        scripts = '<script src="/static/app.js" defer></script>'
    header = Template((TEMPLATES / "header.html").read_text()).substitute(
        overview_current='aria-current="page"' if page == "landing" else "",
        playground_current='aria-current="page"' if page == "workspace" else "",
        docs_current='aria-current="page"' if page in ("docs", "redoc") else "",
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
        skip_target="playground" if is_playground else "api-reference",
        skip_label="the playground" if is_playground else "the API reference",
    )
