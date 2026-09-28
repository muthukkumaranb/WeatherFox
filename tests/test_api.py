"""Tests for skyguard.api.main using FastAPI TestClient.

Run with: python -m pytest -q
"""
import copy
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from skyguard.api.main import create_app, health_check, score_endpoint
from skyguard.contract import validate_verdict

EX = Path(__file__).resolve().parent.parent / "examples"


def load_example(name: str = "input_row.json") -> dict:
    return json.loads((EX / name).read_text())


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


def test_health_check_function():
    res = health_check()
    assert res == {"status": "ok", "version": "0.1.0"}


def test_api_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "0.1.0"}


def test_api_score_endpoint(client):
    row = load_example("input_row.json")
    tid = row["station_id"]
    payload = {"station_window": {tid: [row]}, "target": tid}

    response = client.post("/score", json=payload)
    assert response.status_code == 200
    verdict = response.json()
    assert verdict["station_id"] == tid
    validate_verdict(verdict)


def test_api_stations(client):
    response = client.get("/stations")
    assert response.status_code == 200
    stations = response.json()
    assert isinstance(stations, list)
    assert len(stations) > 0
    assert "id" in stations[0]
    assert "lat" in stations[0]


def test_api_station_series(client):
    response = client.get("/stations/INI0001/series?hours=48")
    assert response.status_code == 200
    data = response.json()
    assert data["station_id"] == "INI0001"
    assert "series" in data


def test_api_alerts(client):
    response = client.get("/alerts")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_api_health_sensors(client):
    response = client.get("/health/sensors")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_api_inject_fault_preset(client):
    payload = {"preset": "55C", "station_id": "INI0001"}
    response = client.post("/inject-fault", json=payload)
    assert response.status_code == 200
    res = response.json()
    assert res["status"] == "ok"
    assert res["injection"]["magnitude"] == 55.0


def test_api_inject_fault_custom(client):
    payload = {
        "station_id": "INI0002",
        "variable": "RH",
        "root_cause": "out_of_range",
        "magnitude": 110.0,
        "duration_hours": 2.0,
    }
    response = client.post("/inject-fault", json=payload)
    assert response.status_code == 200
    res = response.json()
    assert res["status"] == "ok"
    assert res["injection"]["variable"] == "RH"


def test_api_replay_speed(client):
    payload = {"speed_factor": 10.0}
    response = client.post("/replay/speed", json=payload)
    assert response.status_code == 200
    assert response.json()["speed_factor"] == 10.0


def test_api_benchmark(client):
    response = client.get("/benchmark")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data


def test_api_websocket(client):
    with client.websocket_connect("/ws/live") as websocket:
        websocket.send_text("ping")


def test_end_to_end_replay_and_injection():
    import time
    app = create_app()
    with TestClient(app) as client:
        client.post("/replay/speed", json={"speed_factor": 10000.0})
        time.sleep(0.4)

        # 1. Check /stations shows stations
        resp = client.get("/stations")
        assert resp.status_code == 200
        stations = resp.json()
        assert len(stations) > 0

        # 2. Check /stations/INI0001/series is non-empty
        resp_series = client.get("/stations/INI0001/series?hours=48")
        assert resp_series.status_code == 200
        series_data = resp_series.json()["series"]
        assert len(series_data) > 0

        # 3. Inject 55C fault for INI0001
        inj_resp = client.post("/inject-fault", json={"preset": "55C", "station_id": "INI0001"})
        assert inj_resp.status_code == 200

        time.sleep(0.4)

        # 4. Assert an anomaly alert for INI0001 appears in /alerts
        alerts_resp = client.get("/alerts")
        assert alerts_resp.status_code == 200
        alerts = alerts_resp.json()
        assert any(a.get("station_id") == "INI0001" and a.get("label") in ("anomaly", "uncertain") for a in alerts)

