from fastapi.testclient import TestClient

from scout.api.main import app


def test_health_responds_without_db(monkeypatch):
    monkeypatch.setenv("READER_DATABASE_URL", "postgresql://nobody@127.0.0.1:1/none")
    r = TestClient(app).get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert r.json()["db"].startswith("error")
