"""API auth and validation, with the database dependency replaced (no DB needed)."""
import pytest
from fastapi.testclient import TestClient

from scout.agent import tools
from scout.api import main

TOKEN = "test-token-not-a-secret"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("SCOUT_API_TOKEN", TOKEN)
    monkeypatch.setattr(tools, "get_player", lambda conn, a: {"player_id": a.player_id, "name": "Test"})
    monkeypatch.setattr(tools, "predict_value_change", lambda conn, a: {"error": "not in the demo population"})
    main.app.dependency_overrides[main.db] = lambda: None
    yield TestClient(main.app)
    main.app.dependency_overrides.clear()


AUTH = {"Authorization": f"Bearer {TOKEN}"}


def test_every_data_endpoint_needs_the_token(client):
    for method, url in [("get", "/players/1"), ("get", "/players/1/forecast"), ("get", "/players/search?name=ka"),
                        ("post", "/players/compare"), ("post", "/ask")]:
        assert getattr(client, method)(url).status_code == 401, url
        assert getattr(client, method)(url, headers={"Authorization": "Bearer wrong"}).status_code == 401, url


def test_no_token_configured_means_no_access(client, monkeypatch):
    monkeypatch.delenv("SCOUT_API_TOKEN")
    assert client.get("/players/1", headers=AUTH).status_code == 401


def test_valid_requests_and_not_found(client):
    assert client.get("/players/7", headers=AUTH).json() == {"player_id": 7, "name": "Test"}
    assert client.get("/players/7/forecast", headers=AUTH).status_code == 404


@pytest.mark.parametrize("method,url,body", [
    ("get", "/players/0", None),
    ("get", "/players/search?limit=99", None),
    ("get", "/players/search?name=k", None),
    ("get", "/players/search?league=XX1", None),
    ("get", "/players/search?drop=table", None),
    ("post", "/players/compare", {"player_ids": [1]}),
    ("post", "/players/compare", {"player_ids": [1, 2, 3, 4, 5, 6]}),
    ("post", "/ask", {"question": "x" * 501}),
    ("post", "/ask", {"question": "Who?", "model": "claude-opus-5"}),
])
def test_invalid_input_is_rejected(client, method, url, body):
    r = client.post(url, json=body, headers=AUTH) if method == "post" else client.get(url, headers=AUTH)
    assert r.status_code == 422, r.text
