"""Cache-control behavior for the served operator UI."""

from tests.api_client import api_request

from cubos_api import app as app_module


def _dist(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>CubOS</title>")
    (dist / "assets" / "index-abc123.js").write_text("console.log('cubos')")
    return dist


def test_index_html_requires_revalidation(monkeypatch, tmp_path):
    monkeypatch.setattr(app_module, "FRONTEND_DIST", _dist(tmp_path))
    app = app_module.create_app()

    for path in ("/", "/index.html"):
        response = api_request(app, "GET", path)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-cache"


def test_hashed_assets_stay_cacheable(monkeypatch, tmp_path):
    monkeypatch.setattr(app_module, "FRONTEND_DIST", _dist(tmp_path))
    app = app_module.create_app()

    response = api_request(app, "GET", "/assets/index-abc123.js")
    assert response.status_code == 200
    assert "no-cache" not in response.headers.get("cache-control", "")
