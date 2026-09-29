"""Operator feedback processor and recalibration export hook. Owner: Person B.

Exports operator-rejected alerts (e.g., rejected as "genuine_weather") as verified-normal
training examples for Person A's rolling conformal recalibration pipeline.

Hook documentation:
Rolling conformal recalibration uses only:
  1. Verified-normal readings (clean stream / high confidence normal verdicts).
  2. Rejected-as-weather alerts (operator confirmed the deviation was genuine weather, not a sensor fault).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Union

FEEDBACK_FILE_PATH = Path("data/feedback/feedback.jsonl")


def record_feedback(feedback_entry: dict, feedback_file: Union[str, Path] = FEEDBACK_FILE_PATH) -> dict:
    """Append operator feedback entry to feedback.jsonl."""
    f_path = Path(feedback_file)
    f_path.parent.mkdir(parents=True, exist_ok=True)
    with f_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(feedback_entry) + "\n")
    return feedback_entry


def export_rejected_alerts(
    feedback_file: Union[str, Path] = FEEDBACK_FILE_PATH,
    out_file: Union[str, Path, None] = None,
) -> list[dict]:
    """Export operator-rejected alerts as verified-normal calibration examples."""
    f_path = Path(feedback_file)
    if not f_path.exists():
        return []

    exported = []
    with f_path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            entry = json.loads(line)
            if entry.get("state") == "rejected":
                calib_sample = {
                    "alert_id": entry.get("alert_id"),
                    "station_id": entry.get("station_id"),
                    "ts_utc": entry.get("ts_utc"),
                    "recalibration_label": "normal",
                    "reason": entry.get("reason", "genuine_weather"),
                    "by": entry.get("by", "operator"),
                    "note": entry.get("note", ""),
                    "timestamp_recorded": entry.get("timestamp_recorded"),
                }
                exported.append(calib_sample)

    if out_file:
        out_p = Path(out_file)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        with out_p.open("w", encoding="utf-8") as f:
            for item in exported:
                f.write(json.dumps(item) + "\n")

    return exported
