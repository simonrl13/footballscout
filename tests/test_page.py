"""The demo page: served with its own strict CSP, no inline code, no HTML sinks in its scripts, phone-safe basics.
The page logic itself (escaping, link allow-list, waking notice, limits) is tested by node --test (tests/js)."""
import re

import pytest
from fastapi.testclient import TestClient

from scout.agent import tools
from scout.api import main

STATIC = main.STATIC
PAGE = (STATIC / "index.html").read_text(encoding="utf-8")
SCRIPTS = {p.name: p.read_text(encoding="utf-8") for p in STATIC.glob("*.mjs")}
CSS = (STATIC / "style.css").read_text(encoding="utf-8")


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv("PUBLIC_DEMO", raising=False)
    monkeypatch.setenv("SCOUT_API_TOKEN", "test-token-not-a-secret")
    monkeypatch.setattr(tools, "data_as_of", lambda conn: "2026-06-12")
    main.app.dependency_overrides[main.db] = lambda: None
    yield TestClient(main.app)
    main.app.dependency_overrides.clear()


def test_page_and_its_files_are_served_with_the_page_csp(client):
    for path, kind in [("/", "text/html"), ("/static/app.mjs", "text/javascript"), ("/static/render.mjs", "text/javascript"),
                       ("/static/style.css", "text/css")]:
        r = client.get(path)
        assert r.status_code == 200 and r.headers["content-type"].startswith(kind), path
        assert r.headers["Content-Security-Policy"] == main.PAGE_CSP, path
        assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert "script-src 'self';" in main.PAGE_CSP and "unsafe" not in main.PAGE_CSP and "http" not in main.PAGE_CSP
    assert client.get("/players/search").headers["Content-Security-Policy"] == main.CSP  # the API keeps its strict CSP


def test_meta_gives_the_data_date_and_needs_the_token_like_other_data(client):
    assert client.get("/meta").status_code == 401
    r = client.get("/meta", headers={"Authorization": "Bearer test-token-not-a-secret"})
    assert r.json() == {"data_as_of": "2026-06-12"}
    assert "2026-06-12" not in PAGE + "".join(SCRIPTS.values())  # the page reads the date from the API


def test_page_has_no_inline_code():
    scripts = re.findall(r"<script\b([^>]*)>(.*?)</script>", PAGE, re.S)
    assert scripts and all('src="/static/' in attrs and not body.strip() for attrs, body in scripts)
    assert not re.search(r"\son[a-z]+\s*=", PAGE, re.I)  # no inline event handlers
    assert not re.search(r"\sstyle\s*=|<style", PAGE, re.I)
    assert not re.search(r"(src|href)\s*=\s*[\"']?(https?:)?//(?!github\.com/simonrl13/)", PAGE)  # nothing third-party


def test_scripts_use_no_html_sinks():
    for name, js in SCRIPTS.items():
        for sink in ["innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function",
                     "localStorage", "sessionStorage", "setAttribute(\"on", "javascript:"]:
            assert sink not in js, f"{name}: {sink}"


def test_phone_basics():
    viewport = re.search(r'<meta name="viewport" content="([^"]+)"', PAGE).group(1)
    assert "width=device-width" in viewport and "viewport-fit=cover" in viewport
    assert "user-scalable" not in viewport and "maximum-scale" not in viewport  # zoom stays available
    assert re.search(r"textarea\s*{[^}]*font:\s*16px", CSS)  # iOS doesn't zoom into the field
    assert "min-height: 44px" in CSS  # touch targets
    assert not re.search(r"(?<!max-)width:\s*(\d{4,}|[4-9]\d\d)px", CSS)  # no fixed widths wider than a phone
    assert "@media (hover: hover) and (pointer: fine)" in CSS and "prefers-reduced-motion" in CSS
    assert ":hover" not in CSS.split("@media (hover: hover) and (pointer: fine)")[0]  # hover only where it exists


def test_page_texts():
    assert "Market values are crowd estimates, not transfer fees." in PAGE
    examples = re.findall(r"data-example>([^<]+)<", PAGE)
    assert len(examples) == 4 and all(3 <= len(q) <= 500 for q in examples)
