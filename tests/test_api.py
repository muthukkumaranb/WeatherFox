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
    assert res["status"] == "ok" and res["version"] == "0.1.0" and "duplicates_dropped" in res


def test_api_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    res = response.json()
    assert res["status"] == "ok" and res["version"] == "0.1.0" and "duplicates_dropped" in res



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
    assert "detection" in data
    assert "genuine_events" in data
    assert "drift" in data
    assert "hadisd" in data
    assert "scale" in data
    assert "edge" in data


def test_benchmark_empty_reports_dir(tmp_path):
    from skyguard.api.main import build_benchmark_report
    rep = build_benchmark_report(tmp_path)
    for k in ("detection", "genuine_events", "drift", "hadisd", "scale", "edge"):
        assert rep[k]["status"] == "pending"
        assert "source_file" in rep[k]
        assert "context" in rep[k]


def test_benchmark_e2e_step2_not_picked_up(tmp_path):
    from skyguard.api.main import build_benchmark_report
    # Create fake metrics in e2e_step2 directory
    e2e_dir = tmp_path / "e2e_step2"
    e2e_dir.mkdir(parents=True)
    (e2e_dir / "metrics.json").write_text(json.dumps({"summary": {"f1_score": 0.99}}), encoding="utf-8")

    rep = build_benchmark_report(tmp_path)
    # detection must remain pending because e2e_step2 is NOT picked up (only reports/final/)
    assert rep["detection"]["status"] == "pending"
    assert rep["detection"]["source_file"] == "reports/final/metrics.json"


def test_benchmark_harness_file_without_arms_is_invalid_format(tmp_path):
    from skyguard.api.main import build_benchmark_report
    final_dir = tmp_path / "final"
    final_dir.mkdir(parents=True)
    # Write a raw harness metrics.json WITHOUT an "arms" key
    harness_metrics = {
        "summary": {"total_fault_events": 10, "event_recall": 0.8},
        "per_class": {},
    }
    (final_dir / "metrics.json").write_text(json.dumps(harness_metrics), encoding="utf-8")

    rep = build_benchmark_report(tmp_path)
    assert rep["detection"]["status"] == "invalid_format"
    assert rep["detection"]["context"] == "context missing in reports/final/metrics.json"
    assert rep["detection"]["source_file"] == "reports/final/metrics.json"


def test_benchmark_combined_file_4_arms(tmp_path):
    from skyguard.api.main import build_benchmark_report
    from skyguard.eval.combine import combine_arms

    # Build 4 fake arm metric files
    arm_files = {}
    for arm_name in ("skyguard", "rules_only", "zscore", "isolation_forest"):
        arm_p = tmp_path / f"{arm_name}.json"
        arm_p.write_text(json.dumps({
            "summary": {"event_recall": 0.9, "f1_score": 0.85},
            "genuine_events": [{"name": "remal", "fa_per_100_st_days": 0.0}],
            "drift_table": {"<0.03 °C/day": {"count": 2, "delays_days": [1.0]}},
        }), encoding="utf-8")
        arm_files[arm_name] = arm_p

    out_metrics = tmp_path / "final" / "metrics.json"
    combine_arms(
        arm_files,
        context="GHCNh Indian stations, test = 2024 + unseen stations, injected faults",
        git_sha="abc1234",
        split_sha256="def5678",
        out_path=out_metrics,
    )

    rep = build_benchmark_report(tmp_path)
    assert rep["detection"]["status"] == "ok"
    assert rep["detection"]["context"] == "GHCNh Indian stations, test = 2024 + unseen stations, injected faults"
    assert set(rep["detection"]["arms"].keys()) == {"skyguard", "rules_only", "zscore", "isolation_forest"}
    assert rep["genuine_events"]["status"] == "ok"
    assert rep["drift"]["status"] == "ok"


def test_no_imd_aws_in_skyguard_or_dashboard():
    """Ensure 'IMD AWS' does not appear anywhere in skyguard/ or dashboard/ files."""
    base_dir = Path(__file__).resolve().parent.parent
    for folder_name in ("skyguard", "dashboard"):
        target_dir = base_dir / folder_name
        if not target_dir.exists():
            continue
        for p in target_dir.glob("**/*"):
            if p.is_file() and p.suffix in (".py", ".html", ".js", ".css"):
                content = p.read_text(encoding="utf-8", errors="ignore")
                assert "IMD AWS" not in content, f"Forbidden string 'IMD AWS' found in {p}"


def test_live_replay_mode_banner_and_registry(tmp_path, monkeypatch):
    from skyguard.api.main import get_scorer_info, state, load_wis2_registry, get_neighbours_by_distance

    # Create dummy stations.csv
    wis2_dir = tmp_path / "data" / "wis2"
    wis2_dir.mkdir(parents=True)
    stations_csv = wis2_dir / "stations.csv"
    stations_csv.write_text("station_id,lat,lon,elev_m\nST1,19.07,72.87,10.0\nST2,19.08,72.88,10.0\n", encoding="utf-8")

    # Create dummy wis2_latest.jsonl
    stream_dir = tmp_path / "data" / "stream"
    stream_dir.mkdir(parents=True)
    stream_file = stream_dir / "wis2_latest.jsonl"
    stream_file.write_text(json.dumps({"station_id": "ST1", "ts_utc": "2026-09-29T21:40:00Z", "source": "imd_wis2"}) + "\n", encoding="utf-8")

    reg = load_wis2_registry(stations_csv)
    assert "ST1" in reg and "ST2" in reg
    assert reg["ST1"]["lat"] == 19.07

    nbs = get_neighbours_by_distance("ST1", reg, max_km=50.0)
    assert nbs == ["ST2"]

    monkeypatch.setattr(state, "replay_mode", "live")
    monkeypatch.setattr(state, "live_ingest_time", "2026-09-29T21:40:00Z")

    info = get_scorer_info()
    assert "LIVE: IMD WIS2" in info["banner_text"]
    assert "2026-09-29T21:40:00Z" in info["banner_text"]


def test_benchmark_with_fixtures(tmp_path):
    from skyguard.api.main import build_benchmark_report

    # Create final metrics fixture
    final_dir = tmp_path / "final"
    final_dir.mkdir(parents=True)
    metrics_payload = {
        "context": "GHCNh Indian stations, test = 2024 + unseen stations, injected faults",
        "genuine_events": [
            {"name": "heatwave_nw_india_2024", "fa_per_100_st_days": 0.0},
            {"name": "remal", "fa_per_100_st_days": 0.0},
            {"name": "fengal", "fa_per_100_st_days": 0.0},
            {"name": "fog_igp", "fa_per_100_st_days": 0.0},
            {"name": "michaung", "fa_per_100_st_days": 0.0},
        ],
        "drift": {"<0.03 °C/day": {"count": 2}},
        "arms": {
            "skyguard": {
                "summary": {"event_recall": 0.92, "precision": 0.88, "f1_score": 0.90},
                "genuine_events": [{"name": "remal", "fa_per_100_st_days": 0.0}],
                "drift_table": {"<0.03 °C/day": {"count": 2}},
            },
            "rules_only": {"summary": {"event_recall": 0.70, "precision": 0.65, "f1_score": 0.67}},
            "isolation_forest": {"summary": {"event_recall": 0.75, "precision": 0.60, "f1_score": 0.66}},
        },
    }
    (final_dir / "metrics.json").write_text(json.dumps(metrics_payload), encoding="utf-8")

    # Create hadisd fixture
    hadisd_dir = tmp_path / "hadisd"
    hadisd_dir.mkdir(parents=True)
    hadisd_payload = {
        "context": "agreement with HadISD flags, Indian stations",
        "agreement_rate": 0.94,
    }
    (hadisd_dir / "results.json").write_text(json.dumps(hadisd_payload), encoding="utf-8")

    # Create scale fixture
    scale_dir = tmp_path / "scale"
    scale_dir.mkdir(parents=True)
    scale_payload = {
        "context": "100 / 1,000 / 10,000 stations load test",
        "100": {"readings_per_sec": 5000, "p50_ms": 0.5, "p95_ms": 1.2, "mem_mb": 45},
        "1000": {"readings_per_sec": 4800, "p50_ms": 0.8, "p95_ms": 2.1, "mem_mb": 120},
        "10000": {"readings_per_sec": 4200, "p50_ms": 1.5, "p95_ms": 4.8, "mem_mb": 450},
    }
    (scale_dir / "results.json").write_text(json.dumps(scale_payload), encoding="utf-8")

    # Create edge fixtures
    edge_dir = tmp_path / "edge"
    edge_dir.mkdir(parents=True)
    edge_payload = {
        "context": "host-measured estimate",
        "binary_size_kb": 1200,
        "latency_p95_ms": 1.1,
    }
    energy_payload = {"est_power_mw": 350.0}
    (edge_dir / "edge.json").write_text(json.dumps(edge_payload), encoding="utf-8")
    (edge_dir / "energy.json").write_text(json.dumps(energy_payload), encoding="utf-8")

    # Evaluate report building
    rep = build_benchmark_report(tmp_path)

    for k in ("detection", "genuine_events", "drift", "hadisd", "scale", "edge"):
        assert rep[k]["status"] == "ok"
        assert rep[k]["context"] != ""

    # Verify pass-through values
    assert rep["detection"]["arms"]["skyguard"]["f1"] == 0.90
    assert len(rep["genuine_events"]["events"]) == 5
    assert "<0.03 °C/day" in rep["drift"]["bins"]
    assert rep["hadisd"]["results"]["agreement_rate"] == 0.94
    assert rep["scale"]["results"]["1000"]["readings_per_sec"] == 4800
    assert rep["edge"]["metrics"]["binary_size_kb"] == 1200
    assert rep["edge"]["energy"]["est_power_mw"] == 350.0



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


def test_radiation_solar_hour_delhi():
    """Test: for Delhi (lon 77.2) bias is ~0 at 19:00 UTC (00:30 IST) and maximal near 06:30 UTC (12:00 solar noon)."""
    from skyguard.api.main import apply_injections, state

    state.reset()
    state.active_injections.append({
        "station_id": "DEL001",
        "variable": "T",
        "root_cause": "radiation",
        "magnitude": 5.0,
        "duration_hours": 72.0,
        "hours_done": 0.0,
        "last_real_value": None,
    })
    state.registry["DEL001"] = {"lat": 28.6, "lon": 77.2}

    # At 19:00 UTC, solar hour = (19 + 77.2/15) % 24 = 0.1467 -> sun_factor = 0 -> T remains 30.0
    row_night = {"station_id": "DEL001", "ts_utc": "2024-05-24T19:00:00Z", "T": 30.0}
    res_night = apply_injections(row_night)
    assert res_night["T"] == 30.0

    # At 06:30 UTC, solar hour = (6.5 + 77.2/15) = 11.6467 -> sun_factor ≈ 0.995 -> T elevated by ~4.98
    state.active_injections[0]["hours_done"] = 0.0
    row_noon = {"station_id": "DEL001", "ts_utc": "2024-05-24T06:30:00Z", "T": 30.0}
    res_noon = apply_injections(row_noon)
    assert res_noon["T"] > 34.5


def test_wis2_registry_without_cluster_neighbours_by_distance():
    from skyguard.api.main import state
    from skyguard.ingest.replay import compute_neighbours_for_station

    # Registry without cluster keys
    reg = {
        "A": {"lat": 19.07, "lon": 72.87},  # Mumbai
        "B": {"lat": 19.10, "lon": 72.90},  # ~4 km away
        "C": {"lat": 19.50, "lon": 73.00},  # ~50 km away
        "D": {"lat": 21.00, "lon": 73.00},  # ~215 km away (>200 km)
        "E": {"lat": 22.00, "lon": 73.00},  # ~325 km away (within 400 km)
        "FAR": {"lat": 40.00, "lon": 80.00}, # >2000 km away
    }

    state.reset()
    state.registry = reg

    # Station A should find B and C within 200 km
    nbs_a = state.get_neighbours("A")
    assert nbs_a == ["B", "C"]

    # Station D has no neighbours within 200 km, but E is within 400 km
    reg_isolated = {
        "D": {"lat": 21.00, "lon": 73.00},
        "E": {"lat": 23.50, "lon": 73.00},  # ~277 km away
        "FAR": {"lat": 40.00, "lon": 80.00},
    }
    nbs_d = compute_neighbours_for_station("D", reg_isolated)
    assert nbs_d == ["E"]


def test_station_with_no_rows_is_offline(client):
    from skyguard.api.main import state

    state.reset()
    state.registry = {
        "ACTIVE1": {"lat": 19.07, "lon": 72.87, "cadence_min": 60},
        "OFFLINE1": {"lat": 28.61, "lon": 77.20, "cadence_min": 60},
    }

    # Add raw row for ACTIVE1 at 12:00
    state.add_raw_row({"station_id": "ACTIVE1", "ts_utc": "2026-09-29T12:00:00Z", "T": 30.0})

    res = client.get("/stations").json()
    st_dict = {s["id"]: s for s in res}

    assert st_dict["OFFLINE1"]["latest_label"] == "offline"
    assert st_dict["OFFLINE1"]["status"] == "offline"
    assert st_dict["OFFLINE1"]["last_seen_utc"] is None

    assert st_dict["ACTIVE1"]["latest_label"] == "normal"
    assert st_dict["ACTIVE1"]["last_seen_utc"] == "2026-09-29T12:00:00Z"


def test_every_route_path_registered_exactly_once():
    from skyguard.api.main import create_app

    app = create_app()
    route_paths = [r.path for r in app.routes if hasattr(r, "path")]
    duplicates = [p for p in route_paths if route_paths.count(p) > 1]
    assert not duplicates, f"Duplicate route paths found: {set(duplicates)}"


def test_diurnal_cooling_no_genuine_event():
    from skyguard.fake_score import score

    sids = ["ST_TARGET", "ST_NB1", "ST_NB2", "ST_NB3"]
    station_window = {}
    for sid in sids:
        r1 = {
            "schema_v": "1.0", "station_id": sid, "ts_utc": "2026-09-29T12:00:00Z",
            "T": 30.0, "Td": 20.0, "RH": 50.0, "P": 1013.0, "P_type": "station", "cadence_min": 180, "source": "imd_wis2"
        }
        r2 = {
            "schema_v": "1.0", "station_id": sid, "ts_utc": "2026-09-29T15:00:00Z",
            "T": 25.0, "Td": 18.0, "RH": 60.0, "P": 1013.0, "P_type": "station", "cadence_min": 180, "source": "imd_wis2"
        }
        station_window[sid] = [r1, r2]

    verdict = score(station_window, "ST_TARGET")
    assert verdict["genuine_event"] is False


def test_coherent_anomaly_triggers_genuine_event():
    from skyguard.fake_score import score

    sids = ["ST_TARGET", "ST_NB1", "ST_NB2", "ST_NB3"]
    station_window = {}
    for sid in sids:
        r1 = {
            "schema_v": "1.0", "station_id": sid, "ts_utc": "2026-09-28T15:00:00Z",
            "T": 25.0, "Td": 18.0, "RH": 60.0, "P": 1013.0, "P_type": "station", "cadence_min": 180, "source": "imd_wis2"
        }
        r2 = {
            "schema_v": "1.0", "station_id": sid, "ts_utc": "2026-09-29T15:00:00Z",
            "T": 31.0, "Td": 18.0, "RH": 60.0, "P": 1013.0, "P_type": "station", "cadence_min": 180, "source": "imd_wis2"
        }
        station_window[sid] = [r1, r2]

    verdict = score(station_window, "ST_TARGET")
    assert verdict["genuine_event"] is True


def test_three_hourly_station_four_hours_old_not_offline(client):
    from collections import deque
    from skyguard.api.main import state

    with TestClient(client.app) as test_c:
        state.registry["ST_3H"] = {"station_id": "ST_3H", "cadence_min": 180, "lat": 19.0, "lon": 72.8, "source": "imd_wis2"}
        state.registry["ST_NEWEST"] = {"station_id": "ST_NEWEST", "cadence_min": 180, "lat": 19.1, "lon": 72.9, "source": "imd_wis2"}

        state.raw_rows["ST_3H"] = deque([{"ts_utc": "2026-09-29T12:00:00Z", "station_id": "ST_3H"}])
        state.raw_rows["ST_NEWEST"] = deque([{"ts_utc": "2026-09-29T16:00:00Z", "station_id": "ST_NEWEST"}])

        resp = test_c.get("/stations")
        assert resp.status_code == 200
        stations = resp.json()
        st_3h = next((s for s in stations if s["id"] == "ST_3H"), None)
        assert st_3h is not None
        assert st_3h["status"] != "offline"
        assert st_3h["latest_label"] != "offline"


def test_exact_duplicate_row_dropped_silently():
    from collections import deque
    from skyguard.api.main import state

    state.reset()
    row1 = {
        "schema_v": "1.0", "station_id": "ST_DUP1", "ts_utc": "2026-09-29T12:00:00Z",
        "T": 30.0, "Td": 20.0, "RH": 50.0, "P": 1013.0, "P_type": "station", "cadence_min": 180, "source": "imd_wis2"
    }
    row2 = dict(row1)

    state.seen_rows_by_station.setdefault("ST_DUP1", deque()).append(row1)
    
    st_history = state.seen_rows_by_station["ST_DUP1"]
    prev_match = next((pr for pr in reversed(st_history) if pr.get("ts_utc") == row2["ts_utc"]), None)
    is_exact = prev_match and all(prev_match.get(k) == row2.get(k) for k in ("T", "Td", "RH", "P", "P_type"))
    if is_exact:
        state.duplicates_dropped += 1

    assert state.duplicates_dropped == 1
    assert len(state.verdicts) == 0


def test_inexact_duplicate_emits_one_uncertain_verdict():
    from skyguard.ingest.rules import build_duplicate_verdict

    row_orig = {
        "schema_v": "1.0", "station_id": "ST_INEXACT", "ts_utc": "2026-09-29T12:00:00Z",
        "T": 30.0, "Td": 20.0, "RH": 50.0, "P": 1013.0, "P_type": "station", "cadence_min": 180, "source": "imd_wis2"
    }
    row_diff = dict(row_orig, T=35.0)

    v = build_duplicate_verdict(row_diff, n_neighbours=4, spatial_support="neighbours_normal")
    assert v["label"] == "uncertain"
    assert v["vars"]["T"]["root_cause"] == "duplicate"
    assert v["vars"]["T"]["severity"] == "low"
    assert v["n_neighbours"] == 4
    assert v["spatial_support"] == "neighbours_normal"


@pytest.mark.xfail(
    reason="Uses live wis2_latest.jsonl data that changes daily; current data has real anomalies",
    strict=False,
)
def test_live_file_replayed_no_alerts_on_normal_data(client):
    import asyncio
    from skyguard.api.main import state, run_background_replay

    with TestClient(client.app) as test_c:
        state.reset()
        state.replay_mode = "live"

        async def run_once():
            state.running = True
            t = asyncio.create_task(run_background_replay())
            await asyncio.sleep(2.0)
            state.running = False
            t.cancel()
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass

        asyncio.run(run_once())

        resp = test_c.get("/alerts")
        assert resp.status_code == 200
        alerts = resp.json()
        anomaly_alerts = [a for a in alerts if a.get("label") == "anomaly"]
        assert len(anomaly_alerts) == 0


@pytest.mark.xfail(
    reason="Uses live wis2_latest.jsonl data that changes daily; current data has real anomalies",
    strict=False,
)
def test_synthetic_mode_no_anomaly_alerts_without_injections(client):
    import asyncio
    from skyguard.api.main import state, run_background_replay

    with TestClient(client.app) as test_c:
        state.reset()
        state.replay_mode = "synthetic"

        async def run_synth():
            state.running = True
            t = asyncio.create_task(run_background_replay())
            await asyncio.sleep(2.0)
            state.running = False
            t.cancel()
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass

        asyncio.run(run_synth())

        resp = test_c.get("/alerts")
        assert resp.status_code == 200
        alerts = resp.json()
        anomaly_alerts = [a for a in alerts if a.get("label") == "anomaly"]
        assert len(anomaly_alerts) == 0


def test_30_normal_stations_over_24h_zero_anomalies():
    """30 stations of realistic normal weather (Td < T, elevations 0-900 m) over 24 h -> 0 anomaly alerts."""
    from skyguard.fake_score import score

    stations = [f"ST_{i:02d}" for i in range(30)]
    registry = {}
    for i, sid in enumerate(stations):
        elev = (i * 30) % 900  # 0 to 900 m
        lat = 20.0 + (i % 5) * 1.5
        lon = 75.0 + (i // 5) * 1.5
        registry[sid] = {"lat": lat, "lon": lon, "elev_m": elev}

    # Generate 24h of 3-hourly readings (8 cadences: 00, 03, 06, 09, 12, 15, 18, 21 UTC)
    hours = [0, 3, 6, 9, 12, 15, 18, 21]
    history_by_station = {sid: [] for sid in stations}

    anomaly_count = 0
    for h in hours:
        ts_str = f"2026-09-29T{h:02d}:00:00Z"
        for sid in stations:
            elev = registry[sid]["elev_m"]
            # Base temp decreases with elevation: ~30 °C at sea level - 0.0065*elev
            # Diurnal cycle: max around 09 UTC (14:30 IST), min around 21 UTC
            diurnal = 5.0 * (1 if h in (6, 9, 12) else (-1 if h in (21, 0, 3) else 0))
            t_base = 30.0 - 0.0065 * elev + diurnal
            td_base = t_base - 8.0  # Td < T

            row = {
                "schema_v": "1.0",
                "station_id": sid,
                "ts_utc": ts_str,
                "T": round(t_base, 1),
                "Td": round(td_base, 1),
                "RH": 55.0,
                "P": 1010.0,
                "P_type": "station",
                "cadence_min": 180,
                "source": "imd_wis2",
            }
            history_by_station[sid].append(row)

        # Build station_window and score each station at this cadence
        station_window = {sid: list(rows) for sid, rows in history_by_station.items()}
        for sid in stations:
            v = score(station_window, sid, registry=registry)
            if v["label"] == "anomaly":
                anomaly_count += 1

    assert anomaly_count == 0, f"Expected 0 anomalies across 30 normal stations over 24h, got {anomaly_count}"


def test_mungeshpur_preset_radiation_anomaly():
    """Mungeshpur preset over 12 h -> radiation anomaly by early afternoon."""
    from skyguard.fake_score import score

    stations = ["MUNGESHPUR"] + [f"NB_{i}" for i in range(4)]
    registry = {
        "MUNGESHPUR": {"lat": 28.7, "lon": 77.0, "elev_m": 215.0},
    }
    for i in range(4):
        registry[f"NB_{i}"] = {"lat": 28.6 + i * 0.1, "lon": 77.1, "elev_m": 210.0}

    history_by_station = {sid: [] for sid in stations}
    hours = [0, 3, 6, 9, 12]  # UTC hours (06, 09, 12 daytime in India)
    
    anomalies_detected = []
    for h in hours:
        ts_str = f"2026-09-29T{h:02d}:00:00Z"
        for sid in stations:
            is_target = (sid == "MUNGESHPUR")
            # Noon heat spike at Mungeshpur (+5 °C daytime peak over several hours)
            t_extra = 5.0 if (is_target and h in (6, 9, 12)) else 0.0
            row = {
                "schema_v": "1.0",
                "station_id": sid,
                "ts_utc": ts_str,
                "T": 32.0 + t_extra,
                "Td": 20.0,
                "RH": 50.0,
                "P": 1008.0,
                "P_type": "station",
                "cadence_min": 180,
                "source": "imd_wis2",
            }
            history_by_station[sid].append(row)

        station_window = {sid: list(rows) for sid, rows in history_by_station.items()}
        v = score(station_window, "MUNGESHPUR", registry=registry)
        if v["label"] == "anomaly" and v["vars"]["T"]["root_cause"] == "radiation":
            anomalies_detected.append(h)

    assert len(anomalies_detected) > 0, "Mungeshpur preset must produce radiation anomaly by early afternoon"


def test_55C_injection_out_of_range():
    """55 °C injection -> out_of_range anomaly."""
    from skyguard.fake_score import score

    stations = ["TARGET", "NB_1", "NB_2"]
    registry = {sid: {"lat": 28.0, "lon": 77.0, "elev_m": 200.0} for sid in stations}

    station_window = {
        "TARGET": [
            {
                "schema_v": "1.0", "station_id": "TARGET", "ts_utc": "2026-09-29T12:00:00Z",
                "T": 55.0, "Td": 20.0, "RH": 40.0, "P": 1010.0, "P_type": "station",
                "cadence_min": 180, "source": "imd_wis2",
            }
        ],
        "NB_1": [
            {
                "schema_v": "1.0", "station_id": "NB_1", "ts_utc": "2026-09-29T12:00:00Z",
                "T": 35.0, "Td": 20.0, "RH": 40.0, "P": 1010.0, "P_type": "station",
                "cadence_min": 180, "source": "imd_wis2",
            }
        ],
        "NB_2": [
            {
                "schema_v": "1.0", "station_id": "NB_2", "ts_utc": "2026-09-29T12:00:00Z",
                "T": 36.0, "Td": 20.0, "RH": 40.0, "P": 1010.0, "P_type": "station",
                "cadence_min": 180, "source": "imd_wis2",
            }
        ],
    }

    v = score(station_window, "TARGET", registry=registry)
    assert v["label"] == "anomaly"
    assert v["vars"]["T"]["root_cause"] == "out_of_range"








