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
import math
from .rules import build_comms_gap_verdict, build_duplicate_verdict, detect_duplicate


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2.0) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2.0) ** 2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return R * c


def compute_neighbours_for_station(station_id: str, registry: dict[str, dict]) -> list[str]:
    target_info = registry.get(station_id, {})
    t_lat = target_info.get("lat")
    t_lon = target_info.get("lon")

    if t_lat is not None and t_lon is not None:
        try:
            t_lat_f = float(t_lat)
            t_lon_f = float(t_lon)
            distances: list[tuple[float, str]] = []
            for sid, info in registry.items():
                if sid != station_id:
                    lat = info.get("lat")
                    lon = info.get("lon")
                    if lat is not None and lon is not None:
                        d = haversine_km(t_lat_f, t_lon_f, float(lat), float(lon))
                        distances.append((d, sid))
            distances.sort(key=lambda x: x[0])

            within_200 = [sid for d, sid in distances if d <= 200.0]
            if within_200:
                return within_200[:5]

            within_400 = [sid for d, sid in distances if d <= 400.0]
            if within_400:
                return within_400[:3]
        except (ValueError, TypeError):
            pass

    target_cluster = target_info.get("cluster")
    if target_cluster is not None:
        return [sid for sid, info in registry.items() if sid != station_id and info.get("cluster") == target_cluster]

    return []


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


INDIAN_CITIES = [
    # sid, name, lat, lon, elev, base_t, base_rh, base_p, amp_t, cluster
    # Cluster 0: NCR / North (Delhi, Gurugram, Meerut, Rohtak ~70 km)
    ("INI0001", "New Delhi", 28.6139, 77.2090, 216.0, 32.0, 50.0, 1010.0, 4.0, 0),
    ("INI0002", "Gurugram", 28.4595, 77.0266, 217.0, 31.8, 51.0, 1010.0, 4.0, 0),
    ("INI0003", "Meerut", 28.9845, 77.7064, 219.0, 31.5, 52.0, 1010.5, 4.1, 0),
    ("INI0004", "Rohtak", 28.8955, 76.6066, 220.0, 32.2, 49.0, 1009.8, 4.2, 0),
    # Cluster 1: West / Maharashtra (Mumbai, Thane, Pune, Nashik ~140 km)
    ("INI0005", "Mumbai", 19.0760, 72.8777, 14.0, 33.3, 75.0, 1012.0, 3.5, 1),
    ("INI0006", "Thane", 19.2183, 72.9781, 15.0, 33.1, 74.0, 1012.0, 3.5, 1),
    ("INI0007", "Pune", 18.5204, 73.8567, 560.0, 30.5, 60.0, 1011.0, 4.0, 1),
    ("INI0008", "Nashik", 19.9975, 73.7898, 600.0, 30.0, 58.0, 1011.2, 4.1, 1),
    # Cluster 2: South / Tamil Nadu (Chennai, Kanchipuram, Vellore, Puducherry ~135 km)
    ("INI0009", "Chennai", 13.0827, 80.2707, 6.0, 33.3, 70.0, 1012.0, 3.5, 2),
    ("INI0010", "Kanchipuram", 12.8342, 79.7036, 80.0, 33.0, 68.0, 1012.0, 3.6, 2),
    ("INI0011", "Vellore", 12.9165, 79.1325, 220.0, 32.5, 65.0, 1012.5, 3.8, 2),
    ("INI0012", "Puducherry", 11.9416, 79.8083, 3.0, 32.8, 72.0, 1012.2, 3.4, 2),
    # Cluster 3: East / West Bengal (Kolkata, Howrah, Bardhaman, Kharagpur ~115 km)
    ("INI0013", "Kolkata", 22.5726, 88.3639, 9.0, 33.3, 72.0, 1012.0, 3.6, 3),
    ("INI0014", "Howrah", 22.5958, 88.2636, 12.0, 33.2, 73.0, 1012.0, 3.6, 3),
    ("INI0015", "Bardhaman", 23.2324, 87.8615, 40.0, 33.0, 70.0, 1011.5, 3.8, 3),
    ("INI0016", "Kharagpur", 22.3460, 87.2320, 29.0, 33.5, 69.0, 1011.8, 3.9, 3),
]


def generate_synthetic_stream(
    num_stations: int = 16,
    num_clusters: int = 4,
    rows_per_station: int = 10,
    start_ts: str = "2026-09-28T00:00:00Z",
) -> list[dict]:
    """Generate realistic synthetic contract-valid input rows for testing.

    Features per station:
    - Diurnal T cycle (6-10 °C amplitude, peak ~14:00 local solar time)
    - RH anti-correlated with T (keep Td < T)
    - P semidiurnal tide +-1.5 hPa plus slow synoptic drift
    - Gaussian noise (T 0.3 °C, RH 2 %, P 0.3 hPa)
    - Per-city climate offsets across 12 real Indian cities.
    """
    import random
    from datetime import datetime, timedelta, timezone

    dt_start = datetime.fromisoformat(start_ts.replace("Z", "+00:00"))
    rows: list[dict] = []

    for r_idx in range(rows_per_station):
        dt_current = dt_start + timedelta(hours=r_idx)
        ts_utc = dt_current.strftime("%Y-%m-%dT%H:%M:%SZ")
        utc_hour = dt_current.hour + dt_current.minute / 60.0

        for s_idx in range(min(num_stations, len(INDIAN_CITIES))):
            st_id, name, lat, lon, elev, base_t, base_rh, base_p, amp_t, cluster = INDIAN_CITIES[s_idx]

            # Seed for deterministic noise per station and step
            rng = random.Random(hash((st_id, r_idx)))

            # Local Solar Time: LST = (UTC_hour + lon / 15.0) % 24
            lst = (utc_hour + lon / 15.0) % 24.0

            # Diurnal T cycle: peak at 14:00 LST
            t_diurnal = amp_t * math.cos(2.0 * math.pi * (lst - 14.0) / 24.0)
            t_noise = rng.gauss(0.0, 0.3)
            t_val = round(base_t + t_diurnal + t_noise, 1)

            # RH anti-correlated with T (peak RH when T is lowest)
            rh_diurnal = -15.0 * math.cos(2.0 * math.pi * (lst - 14.0) / 24.0)
            rh_noise = rng.gauss(0.0, 2.0)
            rh_val = round(max(15.0, min(95.0, base_rh + rh_diurnal + rh_noise)), 1)

            # Dew point calculation ensuring Td < T
            td_approx = t_val - (100.0 - rh_val) / 5.0
            td_val = round(min(td_approx, t_val - 1.0), 1)

            # P semidiurnal tide +-1.5 hPa (peaks at 10:00 and 22:00 LST) + slow synoptic drift
            p_tide = 1.5 * math.cos(4.0 * math.pi * (lst - 10.0) / 24.0)
            p_drift = 2.0 * math.sin(2.0 * math.pi * r_idx / 120.0)
            p_noise = rng.gauss(0.0, 0.3)
            p_val = round(base_p + p_tide + p_drift + p_noise, 1)

            row = {
                "schema_v": "1.0",
                "station_id": st_id,
                "ts_utc": ts_utc,
                "ingest_ts_utc": ts_utc,
                "seq": r_idx + 1,
                "T": t_val,
                "Td": td_val,
                "RH": rh_val,
                "P": p_val,
                "P_type": "slp",
                "cadence_min": 60,
                "source": "ghcnh_synop",
            }
            rows.append(row)

    return rows


def build_synthetic_registry(num_stations: int = 16, num_clusters: int = 4) -> dict[str, dict]:
    """Build a local station registry dictionary for the 16 real Indian cities."""
    registry: dict[str, dict] = {}
    for idx in range(min(num_stations, len(INDIAN_CITIES))):
        st_id, name, lat, lon, elev, base_t, base_rh, base_p, amp_t, cluster = INDIAN_CITIES[idx]
        registry[st_id] = {
            "name": name,
            "lat": lat,
            "lon": lon,
            "elevation": elev,
            "cluster": cluster,
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
        ts_utc = valid_row.get("ts_utc")

        # Duplicate check
        st_history = seen_rows_by_station.setdefault(target_id, [])

        prev_match = None
        for prev_r in reversed(st_history):
            if ts_utc and prev_r.get("ts_utc") == ts_utc:
                prev_match = prev_r
                break
            try:
                if ts_utc and prev_r.get("ts_utc"):
                    dt1 = datetime.fromisoformat(prev_r["ts_utc"].replace("Z", "+00:00"))
                    dt2 = datetime.fromisoformat(ts_utc.replace("Z", "+00:00"))
                    if abs((dt2 - dt1).total_seconds()) <= 180:
                        prev_match = prev_r
                        break
            except Exception:
                pass

        if prev_match is not None:
            is_exact = all(
                prev_match.get(k) == valid_row.get(k)
                for k in ("T", "Td", "RH", "P", "P_type")
            )
            if is_exact:
                # Drop exact duplicate silently
                continue
            else:
                nb_ids = compute_neighbours_for_station(target_id, registry)
                n_nbs = len(nb_ids)
                support = "neighbours_normal" if n_nbs > 0 else "no_neighbours"
                dup_verdict = build_duplicate_verdict(valid_row, n_neighbours=n_nbs, spatial_support=support)
                verdicts.append(dup_verdict)
                if callback:
                    callback(dup_verdict)
                continue

        st_history.append(valid_row)


        # Push valid non-duplicate row to buffer
        buffers.push(valid_row)

        # Build station_window containing target AND its neighbours
        target_window = buffers.window(target_id)
        station_window: dict[str, list[dict]] = {target_id: target_window}

        # Find neighbours
        if not hasattr(replay, "_nb_cache") or getattr(replay, "_nb_cache_reg_id", None) != id(registry):
            setattr(replay, "_nb_cache", {sid: compute_neighbours_for_station(sid, registry) for sid in registry})
            setattr(replay, "_nb_cache_reg_id", id(registry))

        nb_cache = getattr(replay, "_nb_cache", {})
        nb_ids = nb_cache.get(target_id, [])

        for nb_id in nb_ids:
            nb_w = buffers.window(nb_id)
            if nb_w:
                station_window[nb_id] = nb_w

        # Call scorer
        try:
            verdict = scorer(station_window, target=target_id, registry=registry)
        except TypeError:
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
