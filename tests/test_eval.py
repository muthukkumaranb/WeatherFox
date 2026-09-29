"""Tests for evaluation harness, leak checks, and baselines (STEP 2)."""
from __future__ import annotations

import json
from pathlib import Path
import pytest

from skyguard.eval.harness import evaluate
from skyguard.eval.leak_check import assert_no_forbidden, assert_no_split_leak, check_no_leak
from skyguard.eval.baselines import rules_baseline, zscore_baseline, isolation_forest_baseline
from skyguard.contract import validate_input_row


def test_leak_check_forbidden_features():
    # Should pass for clean feature list
    assert_no_forbidden(["T", "RH", "P", "T_1h_change", "wind_speed"])

    # Should fail for forbidden features
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
    # Clean train set passes
    assert_no_split_leak(clean_train_rows, split_info)

    # Train row with test timestamp fails
    leaky_time_rows = [
        {"station_id": "ST_TRAIN_01", "ts_utc": "2024-02-01T12:00:00Z", "split": "train"},
    ]
    with pytest.raises(AssertionError, match="Split leak detected"):
        assert_no_split_leak(leaky_time_rows, split_info)

    # Train row with unseen test station fails
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
        # Normal reading outside event
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
        # Anomaly inside event
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
    assert metrics["summary"]["clean_false_alarm_rate"] == 0.0


def test_harness_always_anomaly_clean_far():
    labels = []  # No injection events

    verdicts = [
        {
            "schema_v": "1.0",
            "station_id": "ST001",
            "ts_utc": "2024-05-01T09:00:00Z",
            "phase": "final",
            "label": "anomaly",
            "model_version": "v1",
            "spatial_support": "no_neighbours",
            "n_neighbours": 0,
            "genuine_event": False,
            "vars": {"T": {"label": "anomaly", "prob": 0.9, "support_count": 0}},
        },
        {
            "schema_v": "1.0",
            "station_id": "ST001",
            "ts_utc": "2024-05-01T10:00:00Z",
            "phase": "final",
            "label": "anomaly",
            "model_version": "v1",
            "spatial_support": "no_neighbours",
            "n_neighbours": 0,
            "genuine_event": False,
            "vars": {"T": {"label": "anomaly", "prob": 0.9, "support_count": 0}},
        },
    ]

    metrics = evaluate(verdicts, labels)
    # Always-anomaly in clean period -> clean false alarm rate == 1.0
    assert metrics["summary"]["clean_false_alarm_rate"] == 1.0


def test_harness_no_point_adjust():
    # 100-hour fault hit once counts as 1 event detected, not 100
    labels = [
        {
            "schema_v": "1.0",
            "injection_id": "inj_100h",
            "station_id": "ST001",
            "variable": "T",
            "root_cause": "drift",
            "start_ts": "2024-05-01T00:00:00Z",
            "end_ts": "2024-05-05T04:00:00Z",  # 100 hours
            "params": {},
            "difficulty": "medium",
            "seed": 42,
            "split": "test",
        }
    ]

    # Multiple verdict readings during the 100-hour fault
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
    # Total fault events = 1, detected = 1 -> recall = 1.0
    assert metrics["summary"]["total_fault_events"] == 1
    assert metrics["summary"]["detected_fault_events"] == 1
    assert metrics["summary"]["event_recall"] == 1.0


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
            "T": 65.0,  # Gross out-of-range (> 60 C)
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
