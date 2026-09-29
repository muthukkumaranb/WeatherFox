"""End-to-end check script for STEP 2 — Evaluation Harness.

Generates a synthetic run of verdicts and ground-truth injection labels,
runs the evaluation harness, and prints the generated metrics.md report.
"""
from __future__ import annotations

import json
from pathlib import Path
from skyguard.eval.harness import evaluate


def run_e2e_step2() -> None:
    out_dir = Path("reports/e2e_step2")
    out_dir.mkdir(parents=True, exist_ok=True)

    verdicts_path = out_dir / "verdicts.jsonl"
    labels_path = out_dir / "labels.jsonl"

    # Synthetic injection labels (Ground Truth)
    labels = [
        {
            "schema_v": "1.0",
            "injection_id": "inj_001",
            "station_id": "INI0001",
            "variable": "T",
            "root_cause": "out_of_range",
            "start_ts": "2024-05-01T10:00:00Z",
            "end_ts": "2024-05-01T12:00:00Z",
            "params": {"magnitude": 55.0},
            "difficulty": "easy",
            "seed": 42,
            "split": "test",
        },
        {
            "schema_v": "1.0",
            "injection_id": "inj_002",
            "station_id": "INI0002",
            "variable": "RH",
            "root_cause": "frozen",
            "start_ts": "2024-05-01T14:00:00Z",
            "end_ts": "2024-05-01T18:00:00Z",
            "params": {"hours": 4},
            "difficulty": "medium",
            "seed": 43,
            "split": "test",
        },
        {
            "schema_v": "1.0",
            "injection_id": "event_001",
            "station_id": "INI0003",
            "variable": "T",
            "root_cause": "unknown",
            "start_ts": "2024-05-01T08:00:00Z",
            "end_ts": "2024-05-01T16:00:00Z",
            "params": {"kind": "heat_wave"},
            "difficulty": "easy",
            "seed": 44,
            "split": "test",
            "genuine_event": True,
        },
    ]

    # Synthetic Verdicts
    verdicts = [
        # Normal clean baseline
        {
            "schema_v": "1.0",
            "station_id": "INI0001",
            "ts_utc": "2024-05-01T09:00:00Z",
            "phase": "final",
            "label": "normal",
            "model_version": "fake_v1",
            "spatial_support": "neighbours_normal",
            "n_neighbours": 3,
            "genuine_event": False,
            "vars": {"T": {"label": "normal", "prob": 0.0, "support_count": 0}},
        },
        # Inj 1 Detection (INI0001 out_of_range)
        {
            "schema_v": "1.0",
            "station_id": "INI0001",
            "ts_utc": "2024-05-01T10:15:00Z",
            "phase": "final",
            "label": "anomaly",
            "model_version": "fake_v1",
            "spatial_support": "neighbours_normal",
            "n_neighbours": 3,
            "genuine_event": False,
            "vars": {"T": {"label": "anomaly", "root_cause": "out_of_range", "prob": 0.98, "support_count": 0}},
        },
        # Inj 2 Detection (INI0002 frozen)
        {
            "schema_v": "1.0",
            "station_id": "INI0002",
            "ts_utc": "2024-05-01T15:00:00Z",
            "phase": "final",
            "label": "anomaly",
            "model_version": "fake_v1",
            "spatial_support": "neighbours_normal",
            "n_neighbours": 3,
            "genuine_event": False,
            "vars": {"RH": {"label": "anomaly", "root_cause": "frozen", "prob": 0.85, "support_count": 0}},
        },
        # Genuine event station INI0003 (marked as genuine_event: true, normal label)
        {
            "schema_v": "1.0",
            "station_id": "INI0003",
            "ts_utc": "2024-05-01T10:00:00Z",
            "phase": "final",
            "label": "normal",
            "model_version": "fake_v1",
            "spatial_support": "neighbours_also_deviating",
            "n_neighbours": 4,
            "genuine_event": True,
            "vars": {"T": {"label": "normal", "prob": 0.1, "support_count": 0}},
        },
    ]

    with verdicts_path.open("w", encoding="utf-8") as f:
        for v in verdicts:
            f.write(json.dumps(v) + "\n")

    with labels_path.open("w", encoding="utf-8") as f:
        for l in labels:
            f.write(json.dumps(l) + "\n")

    # Run evaluation
    evaluate(verdicts_path, labels_path, output_dir=out_dir)

    print("=== END-TO-END CHECK FOR STEP 2 ===")
    print()
    print((out_dir / "metrics.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    run_e2e_step2()
