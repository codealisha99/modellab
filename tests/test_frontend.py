"""Public page, navigation, and static packaging regression checks."""
from html.parser import HTMLParser
from pathlib import Path
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from app.api.main import app
from app.frontend import render_page


class Page(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.elements = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))


@pytest.mark.parametrize("route", ["/", "/playground", "/docs", "/redoc"])
def test_pages_have_resolvable_navigation_and_local_assets(route):
    with TestClient(app) as client:
        response = client.get(route)
        assert response.status_code == 200
        page = Page(response.text)
        ids = [attrs["id"] for _, attrs in page.elements if "id" in attrs]
        assert len(ids) == len(set(ids))
        assert any(tag == "main" for tag, _ in page.elements)
        current = [attrs for _, attrs in page.elements if attrs.get("aria-current") == "page"]
        assert len(current) == 1
        for tag, attrs in page.elements:
            target = attrs.get("href") if tag in ("a", "link") else attrs.get("src")
            if target and target.startswith("/"):
                assert client.get(target.split("#")[0]).status_code == 200, target
            if target and target.startswith("#"):
                assert target[1:] in ids


@pytest.mark.parametrize("route", ["/", "/playground"])
def test_stream_controls_remain_a_labelled_submittable_form(route):
    with TestClient(app) as client:
        page = Page(client.get(route).text)
    labelled = {a["for"] for t, a in page.elements if t == "label" and "for" in a}
    controls = [(t, a) for t, a in page.elements if t in ("input", "textarea", "select")]
    assert controls and all(a.get("id") in labelled for _, a in controls)
    assert any(t == "form" and a.get("id") == "stream-form" for t, a in page.elements)
    assert any(t == "button" and a.get("id") == "start" and a.get("type") == "submit" for t, a in page.elements)


def test_documentation_helpers_do_not_change_api_schema_or_app_policy():
    with TestClient(app) as client:
        paths = client.get("/openapi.json").json()["paths"]
        assert "/v1/streams" in paths and "/v1/memory/search" in paths
        assert not any(p in paths for p in ("/", "/playground", "/docs", "/redoc", "/docs/oauth2-redirect"))
        assert client.get("/docs/oauth2-redirect").status_code == 200
        csp = client.get("/playground").headers["content-security-policy"]
        assert "unsafe-inline" not in csp and "cdn.jsdelivr.net" not in csp
        assert "connect-src 'self' https://cdn.jsdelivr.net" in client.get("/docs").headers["content-security-policy"]


def test_static_build_matches_served_pages_and_copies_assets():
    root = Path(__file__).resolve().parents[1]
    subprocess.run([sys.executable, "scripts/build_frontend.py"], cwd=root, check=True)
    assert (root / "public/index.html").read_text() == render_page("landing")
    assert (root / "public/playground.html").read_text() == render_page("workspace")
    assert (root / "public/static/app.js").read_bytes() == (root / "app/static/app.js").read_bytes()
