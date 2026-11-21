from copy import deepcopy

from fastapi.testclient import TestClient
import pytest

from app.db import Campaign
from app.keitaro import TrackerError
from app.main import create_app
from conftest import create_campaign


def offer_stream(campaign):
    return next(s for s in campaign["streams"] if s["schema"] == "landings")


def action(client, campaign, name, offer_id, **extra):
    stream_id = offer_stream(campaign)["id"]
    return client.post(f"/api/campaigns/{campaign['id']}/streams/{stream_id}/offers", json={
        "revision": campaign["revision"], "action": name, "offer_id": offer_id, **extra,
    })


def test_create_has_correct_routes_and_bindings(client, campaign):
    assert campaign["name"] == "test_shmelev_campaign"
    remote = campaign["campaign"]
    assert remote["type"] == "position" and remote["state"] == "active"
    assert remote["domain_id"] == 1 and remote["group_id"] == "1" and remote["traffic_source_id"] == 1
    first, second = campaign["streams"]
    assert first["position"] == 1 and first["target"] == "https://www.google.com/"
    assert first["filters"] == [{"name": "country", "mode": "accept", "payload": ["DE"]}]
    assert second["position"] == 2 and second["offers"][0]["share"] == 100
    assert client.get("/api/campaigns").json()[0]["id"] == campaign["id"]
    with client.app.state.sessions() as db:
        assert db.get(Campaign, campaign["id"]).name == campaign["name"]


def test_add_pin_remove_restore_and_remote_shares(client, campaign):
    current = action(client, campaign, "add", 2).json()
    assert [o["share"] for o in offer_stream(current)["offers"]] == [50, 50]
    current = action(client, current, "share", 1, share=70).json()
    assert [o["share"] for o in offer_stream(current)["offers"]] == [70, 30]
    current = action(client, current, "add", 3).json()
    assert [o["share"] for o in offer_stream(current)["offers"]] == [70, 15, 15]
    current = action(client, current, "remove", 2).json()
    assert [o["share"] for o in offer_stream(current)["offers"]] == [70, 30, 0]
    current = action(client, current, "restore", 2).json()
    assert sum(o["share"] for o in offer_stream(current)["offers"] if not o["removed"]) == 100
    stream = client.app.state.service.client.request("GET", f"streams/{offer_stream(current)['id']}")
    assert sum(o["share"] for o in stream["offers"]) == 100
    assert len(client.app.state.service.client.request("GET", "offers")) == 5  # global offers untouched


def test_last_offer_cannot_be_removed(client, campaign):
    before = deepcopy(client.app.state.service.client.data)
    response = action(client, campaign, "remove", 1)
    assert response.status_code == 422
    assert client.app.state.service.client.data == before


def test_duplicate_and_stale_revision(client, campaign):
    assert action(client, campaign, "add", 1).status_code == 409
    assert action(client, campaign, "add", 2).status_code == 200
    assert action(client, campaign, "add", 3).status_code == 409


def test_external_edit_conflicts(client, campaign):
    gateway = client.app.state.service.client
    gateway.request("PUT", f"streams/{offer_stream(campaign)['id']}", json={"name": "Changed externally"})
    assert action(client, campaign, "add", 2).status_code == 409


def test_upstream_error_keeps_local_state(client, campaign):
    gateway = client.app.state.service.client
    request = gateway.request
    before = deepcopy(campaign)

    def failing_request(method, path, **kwargs):
        if method == "PUT":
            raise TrackerError("Test upstream error")
        return request(method, path, **kwargs)

    gateway.request = failing_request
    assert action(client, campaign, "add", 2).status_code == 502
    with client.app.state.sessions() as db:
        row = db.get(Campaign, campaign["id"])
        assert row.revision == before["revision"]
        assert row.snapshot["streams"] == before["streams"]


def test_partial_creation_remains_disabled(client):
    gateway = client.app.state.service.client
    request = gateway.request

    def failing_request(method, path, **kwargs):
        if method == "POST" and path == "streams":
            raise TrackerError("Stream failure")
        return request(method, path, **kwargs)

    gateway.request = failing_request
    response = create_campaign(client)
    assert response.status_code == 502 and "ID" in response.json()["detail"]
    assert gateway.data["campaigns"][0]["state"] == "disabled"


def test_metadata_survives_restart(client, campaign, settings):
    current = action(client, campaign, "add", 2).json()
    current = action(client, current, "share", 1, share=70).json()
    current = action(client, current, "add", 3).json()
    current = action(client, current, "remove", 2).json()
    app = create_app(settings)
    with TestClient(app) as restarted:
        loaded = restarted.post(f"/api/campaigns/{campaign['id']}/refresh").json()
        assert offer_stream(loaded)["offers"][0]["pinned"] is True
        assert offer_stream(loaded)["offers"][0]["share"] == 70
        assert next(o for o in offer_stream(loaded)["offers"] if o["offer_id"] == 2)["removed"] is True


@pytest.mark.parametrize("overrides", [{"country": "ZZ"}, {"country": "RUS"}, {"name": " "}, {"offer_id": 0}, {"domain_id": 999}])
def test_invalid_campaign(client, overrides):
    assert create_campaign(client, **overrides).status_code == 422


def test_other_campaigns_not_editable(client):
    remote = client.app.state.service.client.request("POST", "campaigns", json={"name": "someone_else", "state": "active"})
    assert client.post(f"/api/campaigns/{remote['id']}/refresh").status_code == 403
    assert client.get("/api/campaigns").json() == []


def test_config_does_not_expose_secrets(client):
    data = client.get("/api/config").json()
    assert "api_key" not in data and "password" not in data
    assert data["demo_mode"] is True


def test_same_origin_guard(client):
    assert client.post("/api/campaigns/1/refresh", headers={"Origin": "https://other.example"}).status_code == 403


def test_stats_demo_and_static(client, campaign):
    assert client.get(f"/api/campaigns/{campaign['id']}/stats").json()["total"]["clicks"] == 0
    assert client.get("/").status_code == 200
    assert client.get("/static/app.js").status_code == 200
