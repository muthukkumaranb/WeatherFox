"""Replay engine — builds station_window and feeds score().  Owner: Person B.

Keeps rolling 24 h buffers per station.  Validates rows ONCE at ingest.
"""
from __future__ import annotations

import csv
import json
import time
from pathlib import Path
from typing import Callable, Iterable, Iterator

from ..contract import ingest_row
from ..scorer import score as default_score
from .buffers import BufferPool
from .rules import build_comms_gap_verdict, build_duplicate_verdict, detect_duplicate


def load_replay_stream(source: str | Path | Iterable[dict]) -> Iterator[dict]:
    """Load a stream of contract input rows from a path or an iterable of dicts."""
    if not isinstance(source, (str, Path)):
        yield from source
        return
    path = Path(source)
    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if "seq" in row and row["seq"] != "":
                    row["seq"] = int(row["seq"])
                for float_field in ("T", "Td", "RH", "P", "batt_v"):
                    if float_field in row and row[float_field] != "":
                        row[float_field] = float(row[float_field])
                yield dict(row)
    else:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    yield json.loads(line)


def generate_synthetic_stream(
    num_stations: int = 12,
    num_clusters: int = 3,
    rows_per_station: int = 10,
) -> list[dict]:
    """Generate synthetic contract-valid input rows for testing."""
    rows: list[dict] = []
    base_coords = [
        (28.6139, 77.2090),  # Delhi cluster
        (19.0760, 72.8777),  # Mumbai cluster
        (12.9716, 77.5946),  # Bengaluru cluster
    ]

    for r_idx in range(rows_per_station):
        ts_utc = f"2026-09-28T{r_idx // 4:02d}:{(r_idx % 4) * 15:02d}:00Z"
        for s_idx in range(num_stations):
            cluster_id = s_idx % num_clusters
            st_id = f"INI{s_idx + 1:04d}"

            row = {
                "schema_v": "1.0",
                "station_id": st_id,
                "ts_utc": ts_utc,
                "ingest_ts_utc": ts_utc,
                "seq": r_idx + 1,
                "T": round(30.0 + (r_idx * 0.2) + (cluster_id * 2.0), 1),
                "Td": round(20.0 + (r_idx * 0.1), 1),
                "RH": round(55.0 + (cluster_id * 5.0), 1),
                "P": round(1013.2 - (cluster_id * 10.0), 1),
                "P_type": "slp",
                "cadence_min": 15,
                "source": "ghcnh_synop",
            }
            rows.append(row)
    return rows


def build_synthetic_registry(num_stations: int = 12, num_clusters: int = 3) -> dict[str, dict]:
    """Build a local station registry dictionary for synthetic stations."""
    registry: dict[str, dict] = {}
    base_coords = [
        (28.6139, 77.2090),  # Delhi
        (19.0760, 72.8777),  # Mumbai
        (12.9716, 77.5946),  # Bengaluru
    ]
    for s_idx in range(num_stations):
        cluster_id = s_idx % num_clusters
        st_id = f"INI{s_idx + 1:04d}"
        lat, lon = base_coords[cluster_id]
        registry[st_id] = {
            "lat": round(lat + (s_idx // num_clusters) * 0.05, 4),
            "lon": round(lon + (s_idx // num_clusters) * 0.05, 4),
            "elevation": 200.0,
            "cluster": cluster_id,
        }
    return registry


def replay(
    rows: str | Path | Iterable[dict],
    registry: dict[str, dict] | None = None,
    *,
    scorer: Callable[[dict, str], dict] | None = None,
    speed_factor: float = 0.0,
    callback: Callable[[dict], None] | None = None,
    max_rows_per_station: int = 200,
) -> list[dict]:
    """Replay a stream of contract input rows through rules and detector.

    Parameters
    ----------
    rows:
        Path to file (CSV or JSONL) or iterable of row dicts.
    registry:
        Station metadata dictionary (keyed by station_id). If None, built automatically.
    scorer:
        Scorer function with signature `score(station_window, target)`. Defaults to skyguard.scorer.score.
    speed_factor:
        Replay speed multiplier (0.0 = as fast as possible, 1.0 = real-time, >1.0 = accelerated).
    callback:
        Optional function/queue called with each produced verdict.
    max_rows_per_station:
        Capacity of station ring buffers.

    Returns
    -------
    list[dict]
        Chronological list of all generated contract-valid verdicts.
    """
    if scorer is None:
        scorer = default_score

    stream = load_replay_stream(rows)
    buffers = BufferPool(max_rows_per_station=max_rows_per_station)
    verdicts: list[dict] = []
    seen_rows_by_station: dict[str, list[dict]] = {}

    if registry is None:
        registry = build_synthetic_registry()

    prev_time: float | None = None

    for raw_row in stream:
        # Validate row ONCE at ingest
        valid_row = ingest_row(raw_row)
        if valid_row is None:
            continue

        target_id = valid_row["station_id"]

        # Duplicate check
        st_history = seen_rows_by_station.setdefault(target_id, [])
        st_history.append(valid_row)
        dup_indices = detect_duplicate(st_history)

        if len(st_history) - 1 in dup_indices:
            # Drop duplicate row and emit duplicate verdict
            dup_verdict = build_duplicate_verdict(valid_row)
            verdicts.append(dup_verdict)
            if callback:
                callback(dup_verdict)
            st_history.pop()  # don't buffer duplicate
            continue

        # Push valid non-duplicate row to buffer
        buffers.push(valid_row)

        # Build station_window containing target AND its neighbours
        target_window = buffers.window(target_id)
        station_window: dict[str, list[dict]] = {target_id: target_window}

        # Find neighbours
        nb_ids: list[str] = []
        try:
            from ..data.registry import neighbours
            nb_ids = neighbours(target_id, registry)
        except (ImportError, NotImplementedError):
            # Fallback to local registry or cluster matching
            target_info = registry.get(target_id, {})
            target_cluster = target_info.get("cluster")
            for sid, info in registry.items():
                if sid != target_id:
                    if target_cluster is not None and info.get("cluster") == target_cluster:
                        nb_ids.append(sid)
                    elif target_cluster is None:
                        nb_ids.append(sid)

        for nb_id in nb_ids:
            nb_w = buffers.window(nb_id)
            if nb_w:
                station_window[nb_id] = nb_w

        # Call scorer
        verdict = scorer(station_window, target=target_id)
        verdicts.append(verdict)
        if callback:
            callback(verdict)

        # Simulate replay speed if speed_factor > 0
        if speed_factor > 0.0:
            now_time = time.perf_counter()
            if prev_time is not None:
                elapsed = now_time - prev_time
                delay = (1.0 / speed_factor) - elapsed
                if delay > 0:
                    time.sleep(delay)
            prev_time = time.perf_counter()

    return verdicts
