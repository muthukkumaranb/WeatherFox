"""Tests for the three demo bugs and verification requirements."""
from __future__ import annotations

import json
from skyguard.fake_score import score
from skyguard.ingest.replay import generate_synthetic_stream, build_synthetic_registry, replay


def test_storm_plus_55c_same_station():
    """storm + 55C on the same station -> out_of_range anomaly."""
    registry = build_synthetic_registry()
    target = "INI0001"

    # Generate short history
    stream = generate_synthetic_stream(num_stations=6, rows_per_station=3)
    rows_by_st: dict[str, list[dict]] = {}
    for r in stream:
        rows_by_st.setdefault(r["station_id"], []).append(r)

    # Inject storm (genuine event) on INI0007 affecting INI0001 AND set T=55.0 on INI0001
    for r in rows_by_st["INI0001"]:
        r["is_genuine_event"] = True
    rows_by_st["INI0001"][-1]["T"] = 55.0

    station_window = {sid: rows_by_st[sid] for sid in rows_by_st}
    v = score(station_window, target, registry=registry)

    assert v["label"] == "anomaly"
    assert v["vars"]["T"]["root_cause"] == "out_of_range"
    assert v["genuine_event"] is False


def test_synthetic_series_day_night_range():
    """synthetic series per station has day-night range >= 5 °C."""
    stream = generate_synthetic_stream(num_stations=12, rows_per_station=24)
    rows_by_st: dict[str, list[dict]] = {}
    for r in stream:
        rows_by_st.setdefault(r["station_id"], []).append(r)

    for sid, rows in rows_by_st.items():
        temps = [r["T"] for r in rows if r.get("T") is not None]
        dn_range = max(temps) - min(temps)
        assert dn_range >= 5.0, f"Station {sid} day-night range {dn_range:.1f} °C < 5.0 °C"


def test_frozen_24h_detected_within_6h():
    """frozen 24 h -> anomaly/frozen within 6 h."""
    registry = build_synthetic_registry()
    target = "INI0001"

    # Stream of 24 hourly readings where INI0001 has constant temperature 30.0 °C
    stream = generate_synthetic_stream(num_stations=6, rows_per_station=24)
    rows_by_st: dict[str, list[dict]] = {}
    for r in stream:
        rows_by_st.setdefault(r["station_id"], []).append(r)

    # Freeze INI0001 T at 30.0 °C while neighbours vary
    for r in rows_by_st["INI0001"]:
        r["T"] = 30.0

    detected_hour = None
    for h in range(1, 25):
        current_window = {sid: rows_by_st[sid][:h] for sid in rows_by_st}
        v = score(current_window, target, registry=registry)
        if v["label"] == "anomaly" and v["vars"]["T"].get("root_cause") == "frozen":
            detected_hour = h
            break

    assert detected_hour is not None, "Frozen T was not detected as anomaly/frozen"
    assert detected_hour <= 6, f"Frozen T detected at hour {detected_hour} > 6 h"


def test_offset_plus6_for_24h():
    """offset +6 for 24 h -> root cause offset."""
    registry = build_synthetic_registry()
    target = "INI0001"

    stream = generate_synthetic_stream(num_stations=6, rows_per_station=24)
    rows_by_st: dict[str, list[dict]] = {}
    for r in stream:
        rows_by_st.setdefault(r["station_id"], []).append(r)

    # Apply persistent +6.0 °C offset to INI0001 across day and night
    for r in rows_by_st["INI0001"]:
        r["T"] = round(r["T"] + 6.0, 1)

    # Score at end of 24h
    current_window = {sid: rows_by_st[sid] for sid in rows_by_st}
    v = score(current_window, target, registry=registry)

    assert v["label"] == "anomaly"
    assert v["vars"]["T"]["root_cause"] == "offset"


def test_10_minutes_synthetic_replay_zero_alerts():
    """10 minutes of synthetic replay with no injections -> 0 anomaly alerts."""
    stream = generate_synthetic_stream(num_stations=12, rows_per_station=10)
    registry = build_synthetic_registry()

    verdicts = replay(stream, registry=registry)
    anomaly_alerts = [v for v in verdicts if v.get("label") == "anomaly"]

    assert len(anomaly_alerts) == 0, f"Expected 0 anomaly alerts, got {len(anomaly_alerts)}"
