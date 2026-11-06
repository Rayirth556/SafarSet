"""Constraint 2 over HTTP: the operator lists field conflicts and marks them reviewed."""
import pytest
from fastapi.testclient import TestClient

from safarset.api.app import create_app


@pytest.fixture()
def client():
    with TestClient(create_app()) as c:
        yield c


def test_conflicts_are_listed_and_reviewed_over_http(client):
    assert client.post("/sim/load-scenario", json={"seed": 42}).status_code == 200
    vehicle, pool = next((v["vehicle_id"], p["pool_id"]) for v in client.get("/api/capacity").json()
                         for p in v["pools"] if p["kind"] == "RESERVED")
    url = f"/api/field/vehicles/{vehicle}/vacancy"
    assert client.post(url, json={"pool_id": pool, "from_seg": 0, "to_seg": 1, "vacancy": 4, "observed_at": 850}).status_code == 200
    assert client.post(url, json={"pool_id": pool, "from_seg": 0, "to_seg": 1, "vacancy": 9, "observed_at": 840}).status_code == 200
    listed = client.get("/api/conflicts").json()
    assert listed["open"] == 1 and listed["items"][0]["outcome"] == "STALE_IGNORED"
    cid = listed["items"][0]["id"]
    assert client.post(f"/api/conflicts/{cid}/resolve", json={"note": "TTE reading confirmed"}).status_code == 200
    assert client.get("/api/conflicts").json()["open"] == 0
    assert client.post(f"/api/conflicts/{cid}/resolve", json={"note": "again"}).status_code == 409
