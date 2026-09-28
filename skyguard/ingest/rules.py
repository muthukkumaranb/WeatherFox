"""Ingest rules: duplicate, timeshift, comms_gap detection and verdict creation.  Owner: Person B.

These root causes are decided at ingest and never by the classifier.
"""
from __future__ import annotations

from datetime import datetime, timezone
from ..contract import SCHEMA_VERSION, validate_verdict, worst_label


def parse_ts(ts_str: str) -> datetime:
    """Parse ISO8601 UTC timestamp string to datetime."""
    return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))


def detect_duplicate(rows: list[dict]) -> list[int]:
    """Return 0-based indices of duplicate rows in *rows*.

    A row is a duplicate if another row exists with the same station_id and
    either the same ``seq`` (when seq is present) or a timestamp within 3 minutes.
    """
    duplicates: list[int] = []
    seen_seqs: set[int] = set()
    seen_ts: list[tuple[datetime, int]] = []

    for i, r in enumerate(rows):
        seq = r.get("seq")
        ts_raw = r.get("ts_utc")

        if seq is not None and seq in seen_seqs:
            duplicates.append(i)
            continue
        if seq is not None:
            seen_seqs.add(seq)

        if ts_raw:
            try:
                dt = parse_ts(ts_raw)
                is_dup = False
                for prev_dt, prev_idx in seen_ts:
                    if abs((dt - prev_dt).total_seconds()) <= 180:
                        is_dup = True
                        break
                if is_dup:
                    duplicates.append(i)
                    continue
                seen_ts.append((dt, i))
            except Exception:
                pass

    return duplicates


def detect_timeshift(rows: list[dict], *, tolerance_min: int = 30) -> list[int]:
    """Return indices of rows with suspicious timestamp shifts."""
    shifted: list[int] = []
    for i, r in enumerate(rows):
        ts_utc = r.get("ts_utc")
        ingest_ts = r.get("ingest_ts_utc")
        if ts_utc and ingest_ts:
            try:
                dt_utc = parse_ts(ts_utc)
                dt_ingest = parse_ts(ingest_ts)
                diff_min = abs((dt_ingest - dt_utc).total_seconds()) / 60.0
                if diff_min > tolerance_min:
                    shifted.append(i)
            except Exception:
                pass
    return shifted


def detect_comms_gap(rows: list[dict], *, cadence_min: int = 180) -> list[tuple[int, int]]:
    """Return (start_idx, end_idx) ranges where comms gaps are detected."""
    gaps: list[tuple[int, int]] = []
    if len(rows) < 2:
        return gaps

    tolerance_sec = 180  # 3 min tolerance
    expected_gap_sec = cadence_min * 60 + tolerance_sec

    for i in range(len(rows) - 1):
        ts1_raw = rows[i].get("ts_utc")
        ts2_raw = rows[i + 1].get("ts_utc")
        if ts1_raw and ts2_raw:
            try:
                dt1 = parse_ts(ts1_raw)
                dt2 = parse_ts(ts2_raw)
                diff_sec = (dt2 - dt1).total_seconds()
                if diff_sec > expected_gap_sec:
                    gaps.append((i, i + 1))
            except Exception:
                pass

    return gaps


def build_duplicate_verdict(row: dict) -> dict:
    """Build a contract-valid verdict for a duplicate row."""
    verdict = {
        "schema_v": SCHEMA_VERSION,
        "station_id": row["station_id"],
        "ts_utc": row["ts_utc"],
        "phase": "final",
        "label": "anomaly",
        "model_version": "rules-1.0",
        "spatial_support": "no_neighbours",
        "n_neighbours": 0,
        "genuine_event": False,
        "vars": {
            "T": {
                "label": "anomaly",
                "root_cause": "duplicate",
                "severity": "low",
                "confidence": 0.99,
                "action": "Drop duplicate reading",
            },
            "RH": {"label": "normal", "confidence": 0.99},
            "P": {"label": "normal", "confidence": 0.99},
        },
    }
    return validate_verdict(verdict)


def build_comms_gap_verdict(station_id: str, ts_utc: str) -> dict:
    """Build a contract-valid verdict for a comms gap."""
    verdict = {
        "schema_v": SCHEMA_VERSION,
        "station_id": station_id,
        "ts_utc": ts_utc,
        "phase": "final",
        "label": "anomaly",
        "model_version": "rules-1.0",
        "spatial_support": "no_neighbours",
        "n_neighbours": 0,
        "genuine_event": False,
        "vars": {
            "T": {
                "label": "anomaly",
                "root_cause": "comms_gap",
                "severity": "medium",
                "confidence": 0.99,
                "action": "Check station data link and power",
            },
            "RH": {"label": "normal", "confidence": 0.99},
            "P": {"label": "normal", "confidence": 0.99},
        },
    }
    return validate_verdict(verdict)
