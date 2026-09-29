"""Tests for evaluation harness, leak checks, and baselines (STEP 2 Fixes)."""
from __future__ import annotations

import json
from pathlib import Path
import pytest

from skyguard.eval.harness import evaluate
from skyguard.eval.leak_check import assert_no_forbidden, assert_no_split_leak, check_no_leak
from skyguard.eval.baselines import rules_baseline, zscore_baseline, isolation_forest_baseline


def test_leak_check_forbidden_features():
    assert_no_forbidden(["T", "RH", "P", "T_1h_change", "wind_speed"])

    with pytest.raises(AssertionError, match="Forbidden feature"):
        assert_no_forbidden(["T", "qc", "RH"])

    with pytest.raises(AssertionError, match="Forbidden feature"):
        assert_no_forbidden(["T", "is_injected", "P"])

    with pytest.raises(AssertionError, match="Forbidden feature"):
        assert_no_forbidden(["T", "split", "P"])


def test_leak_check_split_leak():
    split_info = {
        "test_start": "2024-01-01T00:00:00Z",
        "test_unseen_stations": ["ST_TEST_01"],
    }

    clean_train_rows = [
        {"station_id": "ST_TRAIN_01", "ts_utc": "2023-05-01T12:00:00Z", "split": "train"},
    ]
    assert_no_split_leak(clean_train_rows, split_info)

    leaky_time_rows = [
        {"station_id": "ST_TRAIN_01", "ts_utc": "2024-02-01T12:00:00Z", "split": "train"},
    ]
    with pytest.raises(AssertionError, match="Split leak detected"):
        assert_no_split_leak(leaky_time_rows, split_info)

    leaky_station_rows = [
        {"station_id": "ST_TEST_01", "ts_utc": "2023-05-01T12:00:00Z", "split": "train"},
    ]
    with pytest.raises(AssertionError, match="Split leak detected"):
        assert_no_split_leak(leaky_station_rows, split_info)


def test_harness_perfect_detector():
    labels = [
        {
            "schema_v": "1.0",
            "injection_id": "inj_1",
            "station_id": "ST001",
            "variable": "T",
            "root_cause": "out_of_range",
            "start_ts": "2024-05-01T10:00:00Z",
            "end_ts": "2024-05-01T12:00:00Z",
            "params": {},
            "difficulty": "easy",
            "seed": 42,
            "split": "test",
        }
    ]

    verdicts = [
        {
            "schema_v": "1.0",
            "station_id": "ST001",
            "ts_utc": "2024-05-01T09:00:00Z",
            "phase": "final",
            "label": "normal",
            "model_version": "v1",
            "spatial_support": "no_neighbours",
            "n_neighbours": 0,
            "genuine_event": False,
            "vars": {"T": {"label": "normal", "prob": 0.0, "support_count": 0}},
        },
        {
            "schema_v": "1.0",
            "station_id": "ST001",
            "ts_utc": "2024-05-01T10:30:00Z",
            "phase": "final",
            "label": "anomaly",
            "model_version": "v1",
            "spatial_support": "no_neighbours",
            "n_neighbours": 0,
            "genuine_event": False,
            "vars": {"T": {"label": "anomaly", "root_cause": "out_of_range", "prob": 0.9, "support_count": 0}},
        },
    ]

    metrics = evaluate(verdicts, labels)
    assert metrics["summary"]["f1_score"] == 1.0
    assert metrics["summary"]["event_recall"] == 1.0


def test_harness_always_anomaly_stress_test():
    """Stress test: 30 days x 2 stations always flagging anomaly.

    Must achieve F1 < 0.1 and genuine_event_fa_per_100_st_days > 0.
    """
    labels = [
        {
            "schema_v": "1.0",
            "injection_id": "inj_single",
            "station_id": "ST001",
            "variable": "T",
            "root_cause": "out_of_range",
            "start_ts": "2024-05-01T10:00:00Z",
            "end_ts": "2024-05-01T12:00:00Z",  # 2-hour fault event
            "params": {},
            "difficulty": "easy",
            "seed": 42,
            "split": "test",
        }
    ]

    events_cfg = [
        {
            "name": "Synthetic Heat Wave",
            "type": "heat_wave",
            "start": "2024-05-10T00:00:00Z",
            "end": "2024-05-15T00:00:00Z",
            "lat_min": 10.0,
            "lat_max": 30.0,
            "lon_min": 70.0,
            "lon_max": 90.0,
        }
    ]

    # Generate 30 days of 1-hour readings for 2 stations (ST001, ST002) = 720 hours x 2 = 1440 readings
    verdicts = []
    for st in ("ST001", "ST002"):
        for d in range(1, 31):
            for h in range(24):
                ts = f"2024-05-{d:02d}T{h:02d}:00:00Z"
                verdicts.append({
                    "schema_v": "1.0",
                    "station_id": st,
                    "ts_utc": ts,
                    "phase": "final",
                    "label": "anomaly",
                    "model_version": "always_anomaly_v1",
                    "spatial_support": "no_neighbours",
                    "n_neighbours": 0,
                    "genuine_event": False,
                    "vars": {"T": {"label": "anomaly", "root_cause": "out_of_range", "prob": 0.99, "support_count": 0}},
                })

    registry = {
        "ST001": {"lat": 25.0, "lon": 75.0},
        "ST002": {"lat": 25.0, "lon": 75.0},
    }

    metrics = evaluate(verdicts, labels, events_cfg=events_cfg, registry_input=registry)

    # 1. Continuous anomaly split every 24h -> F1 MUST be < 0.1
    f1 = metrics["summary"]["f1_score"]
    assert f1 < 0.1, f"Expected F1 < 0.1 for always-anomaly detector, got {f1}"

    # 2. Genuine event FA per 100 station days MUST be > 0
    genuine_fa = metrics["summary"]["genuine_event_fa_per_100_st_days"]
    assert genuine_fa > 0.0, f"Expected genuine_event_fa_per_100_st_days > 0, got {genuine_fa}"


def test_harness_never_anomaly():
    """Never-anomaly detector must get recall 0."""
    labels = [
        {
            "schema_v": "1.0",
            "injection_id": "inj_1",
            "station_id": "ST001",
            "variable": "T",
            "root_cause": "out_of_range",
            "start_ts": "2024-05-01T10:00:00Z",
            "end_ts": "2024-05-01T12:00:00Z",
            "params": {},
            "difficulty": "easy",
            "seed": 42,
            "split": "test",
        }
    ]

    verdicts = [
        {
            "schema_v": "1.0",
            "station_id": "ST001",
            "ts_utc": "2024-05-01T11:00:00Z",
            "phase": "final",
            "label": "normal",
            "model_version": "never_anomaly_v1",
            "spatial_support": "no_neighbours",
            "n_neighbours": 0,
            "genuine_event": False,
            "vars": {"T": {"label": "normal", "prob": 0.0, "support_count": 0}},
        }
    ]

    metrics = evaluate(verdicts, labels)
    assert metrics["summary"]["event_recall"] == 0.0
    assert metrics["summary"]["f1_score"] == 0.0


def test_harness_no_point_adjust():
    """100-hour fault hit once counts as 1 detected event (recall = 1.0)."""
    labels = [
        {
            "schema_v": "1.0",
            "injection_id": "inj_100h",
            "station_id": "ST001",
            "variable": "T",
            "root_cause": "drift",
            "start_ts": "2024-05-01T00:00:00Z",
            "end_ts": "2024-05-05T04:00:00Z",
            "params": {"rate": 0.08},
            "difficulty": "medium",
            "seed": 42,
            "split": "test",
        }
    ]

    verdicts = []
    for h in range(100):
        day = 1 + h // 24
        ts = f"2024-05-{day:02d}T{h % 24:02d}:00:00Z"
        verdicts.append({
            "schema_v": "1.0",
            "station_id": "ST001",
            "ts_utc": ts,
            "phase": "final",
            "label": "anomaly" if h == 50 else "normal",
            "model_version": "v1",
            "spatial_support": "no_neighbours",
            "n_neighbours": 0,
            "genuine_event": False,
            "vars": {"T": {"label": "anomaly" if h == 50 else "normal", "prob": 0.9 if h == 50 else 0.0, "support_count": 0}},
        })

    metrics = evaluate(verdicts, labels)
    assert metrics["summary"]["total_fault_events"] == 1
    assert metrics["summary"]["detected_fault_events"] == 1
    assert metrics["summary"]["event_recall"] == 1.0


def test_genuine_event_registry_and_station_days():
    # Registry with 2 inside bbox, 1 outside, 1 unlisted (no coords)
    registry = {
        "ST_IN_1": {"lat": 28.5, "lon": 77.2},  # Inside Delhi bbox [26..30, 75..80]
        "ST_IN_2": {"lat": 29.0, "lon": 78.0},  # Inside Delhi bbox
        "ST_OUT": {"lat": 13.0, "lon": 80.0},   # Outside (Chennai)
    }

    events_cfg = [
        {
            "name": "Delhi Heat Wave",
            "type": "heat_wave",
            "start": "2024-05-01T00:00:00Z",
            "end": "2024-05-05T00:00:00Z",  # 4 days
            "lat_min": 26.0,
            "lat_max": 30.0,
            "lon_min": 75.0,
            "lon_max": 80.0,
        }
    ]

    verdicts = [
        # ST_IN_1 verdict
        {"schema_v": "1.0", "station_id": "ST_IN_1", "ts_utc": "2024-05-02T12:00:00Z", "phase": "final", "label": "normal", "model_version": "v1", "spatial_support": "no_neighbours", "n_neighbours": 0, "genuine_event": True, "vars": {"T": {"label": "normal", "prob": 0.0, "support_count": 0}}},
        # ST_IN_2 verdict
        {"schema_v": "1.0", "station_id": "ST_IN_2", "ts_utc": "2024-05-03T12:00:00Z", "phase": "final", "label": "normal", "model_version": "v1", "spatial_support": "no_neighbours", "n_neighbours": 0, "genuine_event": True, "vars": {"T": {"label": "normal", "prob": 0.0, "support_count": 0}}},
        # ST_OUT verdict
        {"schema_v": "1.0", "station_id": "ST_OUT", "ts_utc": "2024-05-02T12:00:00Z", "phase": "final", "label": "normal", "model_version": "v1", "spatial_support": "no_neighbours", "n_neighbours": 0, "genuine_event": False, "vars": {"T": {"label": "normal", "prob": 0.0, "support_count": 0}}},
        # ST_NO_COORDS verdict
        {"schema_v": "1.0", "station_id": "ST_NO_COORDS", "ts_utc": "2024-05-02T12:00:00Z", "phase": "final", "label": "normal", "model_version": "v1", "spatial_support": "no_neighbours", "n_neighbours": 0, "genuine_event": False, "vars": {"T": {"label": "normal", "prob": 0.0, "support_count": 0}}},
    ]

    metrics = evaluate(verdicts, [], events_cfg=events_cfg, registry_input=registry)
    g_rep = metrics["genuine_events"][0]

    # 2 stations in bbox x 4 days = 8 station-days
    assert g_rep["stations_in_bbox"] == 2
    assert g_rep["station_days"] == 8.0
    # 1 station with no coordinates skipped
    assert g_rep["skipped_no_coords"] == 1


def test_baselines_outputs():
    rows = [
        {
            "schema_v": "1.0",
            "station_id": "ST001",
            "ts_utc": "2024-05-01T00:00:00Z",
            "source": "ghcnh_synop",
            "lat": 12.97,
            "lon": 77.59,
            "elevation_m": 920.0,
            "T": 65.0,  # Out of range
            "RH": 50.0,
            "P": 1013.0,
            "quality": "raw",
        },
        {
            "schema_v": "1.0",
            "station_id": "ST001",
            "ts_utc": "2024-05-01T01:00:00Z",
            "source": "ghcnh_synop",
            "lat": 12.97,
            "lon": 77.59,
            "elevation_m": 920.0,
            "T": 25.0,
            "RH": 50.0,
            "P": 1013.0,
            "quality": "raw",
        },
    ]

    r_verdicts = rules_baseline(rows)
    assert len(r_verdicts) == 2
    assert r_verdicts[0]["label"] == "anomaly"

    z_verdicts = zscore_baseline(rows)
    assert len(z_verdicts) == 2

    if_verdicts = isolation_forest_baseline(rows)
    assert len(if_verdicts) == 2
