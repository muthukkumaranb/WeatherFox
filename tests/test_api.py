"""Tests for skyguard.api.main using FastAPI TestClient.

Run with: python -m pytest -q
"""
import copy
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from skyguard.api.main import create_app, health_check, score_endpoint, get_scorer_info
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
    # 55C preset is an out_of_range fault, NOT a spike
    assert res["injection"]["root_cause"] == "out_of_range"


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


def test_api_inject_fault_radiation_preset(client):
    payload = {"preset": "radiation", "station_id": "INI0001"}
    response = client.post("/inject-fault", json=payload)
    assert response.status_code == 200
    res = response.json()
    assert res["status"] == "ok"
    assert res["injection"]["root_cause"] == "radiation"
    assert res["injection"]["duration_hours"] == 72.0


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


def test_api_scorer_info(client):
    response = client.get("/scorer-info")
    assert response.status_code == 200
    info = response.json()
    assert "backend" in info
    assert "model_version" in info
    assert "banner_text" in info
    assert "banner_level" in info
    # Default backend is fake
    assert info["backend"] == "fake"
    assert "DEMO MODE" in info["banner_text"]


def test_scorer_info_function():
    info = get_scorer_info()
    assert info["backend"] == "fake"
    assert info["banner_level"] == "warning"
    assert "fake" in info["banner_text"].lower()


def test_api_inject_event(client):
    payload = {"station_id": "INI0001", "kind": "heat_wave", "duration_hours": 2.0}
    response = client.post("/inject-event", json=payload)
    assert response.status_code == 200
    res = response.json()
    assert res["status"] == "ok"
    assert res["event"]["kind"] == "heat_wave"
    assert len(res["event"]["affected_stations"]) > 1  # target + neighbours


def test_api_inject_event_unknown_kind(client):
    payload = {"station_id": "INI0001", "kind": "tornado"}
    response = client.post("/inject-event", json=payload)
    assert response.status_code == 400


def test_api_inject_event_squall(client):
    payload = {"station_id": "INI0001", "kind": "squall", "duration_hours": 1.0}
    response = client.post("/inject-event", json=payload)
    assert response.status_code == 200
    res = response.json()
    assert res["event"]["kind"] == "squall"


def test_api_inject_event_cyclone(client):
    payload = {"station_id": "INI0001", "kind": "cyclone", "duration_hours": 6.0}
    response = client.post("/inject-event", json=payload)
    assert response.status_code == 200
    res = response.json()
    assert res["event"]["kind"] == "cyclone"


def test_api_stations_has_genuine_event(client):
    response = client.get("/stations")
    assert response.status_code == 200
    stations = response.json()
    # All stations should have genuine_event field
    assert all("genuine_event" in s for s in stations)


def test_api_websocket(client):
    with client.websocket_connect("/ws/live") as websocket:
        websocket.send_text("ping")


def test_websocket_live_verdicts():
    app = create_app()
    with TestClient(app) as client:
        client.post("/replay/speed", json={"speed_factor": 10000.0})
        with client.websocket_connect("/ws/live") as websocket:
            data = websocket.receive_json()
            assert "station_id" in data
            assert "label" in data


def test_real_uvicorn_server_responsiveness_and_replay():
    """Start real uvicorn server in a background thread and assert responsiveness and replay behavior."""
    import json
    import threading
    import time
    import urllib.request
    import uvicorn

    app = create_app()
    config = uvicorn.Config(app=app, host="127.0.0.1", port=8989, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    time.sleep(1.0)  # Wait for server startup

    try:
        base_url = "http://127.0.0.1:8989"

        # Set speed factor high for fast replay in test
        req = urllib.request.Request(
            f"{base_url}/replay/speed",
            data=json.dumps({"speed_factor": 10000.0}).encode(),
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req)

        # 1. Assert /health answers in < 1 s five times in a row
        for _ in range(5):
            t0 = time.time()
            resp = urllib.request.urlopen(f"{base_url}/health", timeout=1.0)
            t1 = time.time()
            assert resp.status == 200
            assert (t1 - t0) < 1.0

        # Wait a bit for replay rows to populate
        time.sleep(1.0)

        # 2. Assert /stations shows verdict labels
        resp_st = urllib.request.urlopen(f"{base_url}/stations")
        assert resp_st.status == 200
        stations = json.loads(resp_st.read().decode())
        assert len(stations) > 0
        assert any(s.get("latest_label") is not None for s in stations)

        # 3. Assert /stations/{id}/series has rows with increasing ts_utc
        target_sid = stations[0]["id"]
        resp_ser = urllib.request.urlopen(f"{base_url}/stations/{target_sid}/series?hours=48")
        assert resp_ser.status == 200
        ser_data = json.loads(resp_ser.read().decode()).get("series", [])
        assert len(ser_data) >= 2
        ts_list = [r["ts_utc"] for r in ser_data]
        assert ts_list == sorted(ts_list)
        assert len(set(ts_list)) == len(ts_list)

        # 4. Inject 55C fault and assert an anomaly alert appears in /alerts
        inj_req = urllib.request.Request(
            f"{base_url}/inject-fault",
            data=json.dumps({"preset": "55C", "station_id": target_sid}).encode(),
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(inj_req)

        time.sleep(1.0)

        alerts_resp = urllib.request.urlopen(f"{base_url}/alerts")
        assert alerts_resp.status == 200
        alerts = json.loads(alerts_resp.read().decode())
        assert any(a.get("station_id") == target_sid and a.get("label") in ("anomaly", "uncertain") for a in alerts)

    finally:
        server.should_exit = True


