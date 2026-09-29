"""Tests for Step 3: Operator feedback and WMO QC export."""
from __future__ import annotations

import json
from pathlib import Path
from fastapi.testclient import TestClient

from skyguard.api.main import create_app, state
from skyguard.eval.feedback import export_rejected_alerts, record_feedback


def test_alert_ack_and_feedback(tmp_path: Path):
    app = create_app()
    client = TestClient(app)

    state.reset()
    # Add a sample verdict
    verdict = {
        "schema_v": "1.0",
        "station_id": "INI0001",
        "ts_utc": "2024-05-01T12:00:00Z",
        "phase": "final",
        "label": "anomaly",
        "model_version": "fake_v1",
        "spatial_support": "no_neighbours",
        "n_neighbours": 0,
        "genuine_event": False,
        "vars": {"T": {"label": "anomaly", "root_cause": "out_of_range", "prob": 0.95, "support_count": 0}},
    }
    state.add_verdict(verdict)

    # 1. GET /alerts returns open alert
    res = client.get("/alerts")
    assert res.status_code == 200
    alerts = res.json()
    assert len(alerts) == 1
    assert alerts[0]["state"] == "open"

    # 2. Reject alert as genuine_weather via POST /alerts/{id}/ack
    alert_id = "INI0001_2024-05-01T12:00:00Z"
    ack_res = client.post(
        f"/alerts/{alert_id}/ack",
        json={
            "state": "rejected",
            "reason": "genuine_weather",
            "note": "Operator confirmed heat wave",
            "by": "operator_test",
        },
    )
    assert ack_res.status_code == 200
    assert ack_res.json()["state"] == "rejected"

    # 3. GET /alerts?state=rejected returns rejected alert
    res_rejected = client.get("/alerts?state=rejected")
    assert res_rejected.status_code == 200
    r_alerts = res_rejected.json()
    assert len(r_alerts) == 1
    assert r_alerts[0]["reason"] == "genuine_weather"


def test_feedback_export(tmp_path: Path):
    fb_file = tmp_path / "feedback.jsonl"
    out_file = tmp_path / "exported.jsonl"

    record_feedback(
        {
            "alert_id": "INI0001_123",
            "station_id": "INI0001",
            "ts_utc": "2024-05-01T12:00:00Z",
            "state": "rejected",
            "reason": "genuine_weather",
            "by": "operator",
            "note": "heat wave",
            "timestamp_recorded": "2024-05-01T12:05:00Z",
        },
        feedback_file=fb_file,
    )

    exported = export_rejected_alerts(feedback_file=fb_file, out_file=out_file)
    assert len(exported) == 1
    assert exported[0]["recalibration_label"] == "normal"
    assert exported[0]["reason"] == "genuine_weather"


def test_qc_export_csv():
    app = create_app()
    client = TestClient(app)

    state.reset()
    state.add_raw_row({"station_id": "INI0001", "ts_utc": "2024-05-01T12:00:00Z", "T": 55.0, "RH": 40.0, "P": 1013.0})
    state.add_verdict({
        "schema_v": "1.0",
        "station_id": "INI0001",
        "ts_utc": "2024-05-01T12:00:00Z",
        "phase": "final",
        "label": "anomaly",
        "model_version": "fake_v1",
        "spatial_support": "no_neighbours",
        "n_neighbours": 0,
        "genuine_event": False,
        "vars": {
            "T": {"label": "anomaly", "root_cause": "out_of_range", "prob": 0.95, "support_count": 0, "corrected": {"value": 35.0, "sigma": 0.5}},
            "RH": {"label": "normal", "prob": 0.0, "support_count": 0},
            "P": {"label": "normal", "prob": 0.0, "support_count": 0},
        },
    })

    res = client.get("/export?station_id=INI0001")
    assert res.status_code == 200
    assert "text/csv" in res.headers["content-type"]
    csv_text = res.text
    assert "ts_utc,station_id,T,RH,P,T_flag,RH_flag,P_flag,T_corrected,T_sigma" in csv_text
    # Check flag for T is 3 (anomaly) and RH is 0 (good)
    assert "INI0001,55.0,40.0,1013.0,3,0,0,35.0,0.5" in csv_text
