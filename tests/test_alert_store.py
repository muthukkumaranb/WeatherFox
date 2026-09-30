"""Alerts must survive heavy traffic from other stations; series labels must never invent "normal"."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from skyguard.api import main as api
from skyguard.api.main import build_incidents


def _ts(h: int) -> str:
    return (datetime(2024, 5, 25, tzinfo=timezone.utc) + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _verdict(sid: str, h: int, label: str = "normal", cause: str | None = None) -> dict:
    t = {"label": label}
    if cause:
        t.update(root_cause=cause, confidence=0.98, severity="high", action="inspect")
    return {
        "station_id": sid, "ts_utc": _ts(h), "label": label,
        "vars": {"T": t, "RH": {"label": "normal"}, "P": {"label": "normal"}},
    }


@pytest.fixture()
def state():
    s = api.StateManager()
    yield s
    s.reset()


def test_alerts_survive_other_stations_traffic(state):
    for h in range(6):
        state.add_verdict(_verdict("INI0001", h, "anomaly", "out_of_range"))
    # 16 stations x 240 h of normal verdicts: far more than the 2,000-entry rolling buffer.
    for h in range(6, 246):
        for i in range(2, 18):
            state.add_verdict(_verdict(f"INI{i:04d}", h))
    ids = [a for a in state.alerts if a.startswith("INI0001_")]
    assert len(ids) == 6
    incidents = build_incidents(state.alerts, state.alerts_feedback)
    assert len(incidents) == 1
    inc = incidents[0]
    assert (inc["station_id"], inc["variable"], inc["root_cause"], inc["n_readings"]) == (
        "INI0001", "T", "out_of_range", 6)
    assert inc["start_ts"] == _ts(0) and inc["end_ts"] == _ts(5)


def test_incidents_split_on_gap(state):
    for h in (0, 1, 2, 20, 21):
        state.add_verdict(_verdict("INI0003", h, "anomaly", "frozen"))
    incidents = build_incidents(state.alerts, state.alerts_feedback, gap_hours=6)
    assert sorted(i["n_readings"] for i in incidents) == [2, 3]


def test_alert_cap_evicts_closed_first(state, monkeypatch):
    monkeypatch.setattr(api, "ALERT_CAP", 3)
    state.add_verdict(_verdict("INI0001", 0, "anomaly", "spike"))
    state.alerts_feedback["INI0001_" + _ts(0)] = {"state": "resolved"}
    for h in range(1, 4):
        state.add_verdict(_verdict("INI0002", h, "anomaly", "spike"))
    assert "INI0001_" + _ts(0) not in state.alerts
    assert len(state.alerts) == 3


def test_series_label_unscored_without_verdict_and_alerts_endpoint():
    api.state.reset()
    try:
        api.state.add_raw_row({"station_id": "INI0001", "ts_utc": _ts(0), "T": 30.0, "RH": 50.0, "P": 1008.0})
        api.state.add_raw_row({"station_id": "INI0001", "ts_utc": _ts(1), "T": 55.0, "RH": 50.0, "P": 1008.0})
        api.state.add_verdict(_verdict("INI0001", 1, "anomaly", "out_of_range"))
        for h in range(2, 300):
            for i in range(2, 18):
                api.state.add_verdict(_verdict(f"INI{i:04d}", h))
        client = TestClient(api.create_app())  # no lifespan: replay not started
        series = client.get("/stations/INI0001/series").json()["series"]
        assert [p["label"] for p in series] == ["unscored", "anomaly"]
        alerts = client.get("/alerts").json()
        assert [a["alert_id"] for a in alerts] == ["INI0001_" + _ts(1)]
        incidents = client.get("/incidents").json()
        assert incidents[0]["root_cause"] == "out_of_range"
    finally:
        api.state.reset()
