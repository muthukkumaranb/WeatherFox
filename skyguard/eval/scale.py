"""Scale test for SkyGuard pipeline.  Owner: Person C.

Replays exactly 5,000 readings per network size (100, 1,000, 10,000 stations)
through validate + rule_gate + scorer with SKYGUARD_SCORER=fake, in-process,
neighbours by distance (precomputed once). 3 runs each.

Records per size:
  - n_readings, readings_per_sec mean/min/max, p50/p95 ms,
  - peak_memory_mb (tracemalloc), required_rate_per_sec (stations/3600),
  - cpu, python, scorer, git_sha.

Writes reports/scale/results.json and reports/scale/scale.png.
If full run would exceed 5 minutes, reduces to 2000 readings.
"""
from __future__ import annotations

import json
import math
import os
import platform
import random
import subprocess
import sys
import time
import tracemalloc
from pathlib import Path
from typing import NamedTuple

TARGET_READINGS = 5_000
FALLBACK_READINGS = 2_000
MAX_SECONDS = 300  # 5 minutes
SIZES = [100, 1_000, 10_000]
N_RUNS = 3


def get_git_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True, cwd=Path(__file__).parent.parent
        ).stdout.strip()
    except Exception:
        return "unknown"


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def generate_stations(n: int, seed: int = 42) -> dict[str, dict]:
    """Generate synthetic station registry with lat/lon in India bounds."""
    rng = random.Random(seed)
    registry = {}
    for i in range(n):
        sid = f"s{i:06d}"
        lat = rng.uniform(8.0, 37.0)
        lon = rng.uniform(68.0, 97.0)
        registry[sid] = {"lat": lat, "lon": lon, "cadence_min": 60, "elevation": 0.0}
    return registry


def compute_neighbours(registry: dict[str, dict], radius_km: float = 150.0) -> dict[str, list[str]]:
    """Precompute neighbours within radius_km using a grid-cell approach (O(n) avg).

    Divides the lat/lon space into cells of approximately radius_km size.
    Only checks haversine for stations in the same or adjacent cells.
    This replaces the O(n^2) brute-force approach.
    """
    # Grid cell size: radius_km in degrees
    cell_deg_lat = radius_km / 111.0  # 1 deg lat ~ 111 km
    cell_deg_lon = radius_km / 96.0   # at 25degN, 1 deg lon ~ 96 km

    # Build spatial grid
    grid: dict = {}
    sid_coords: dict = {}
    for sid, meta in registry.items():
        lat, lon = meta["lat"], meta["lon"]
        sid_coords[sid] = (lat, lon)
        ci = int(lat / cell_deg_lat)
        cj = int(lon / cell_deg_lon)
        key = (ci, cj)
        if key not in grid:
            grid[key] = []
        grid[key].append(sid)

    neighbours: dict[str, list[str]] = {sid: [] for sid in registry}
    for sid_a, (lat_a, lon_a) in sid_coords.items():
        ci = int(lat_a / cell_deg_lat)
        cj = int(lon_a / cell_deg_lon)
        # Check this cell and all 8 adjacent cells
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                for sid_b in grid.get((ci + di, cj + dj), []):
                    if sid_b == sid_a:
                        continue
                    lat_b, lon_b = sid_coords[sid_b]
                    d = haversine_km(lat_a, lon_a, lat_b, lon_b)
                    if d <= radius_km:
                        neighbours[sid_a].append(sid_b)
    return neighbours


def generate_rows(stations: list[str], n_readings: int, seed: int = 0) -> list[dict]:
    """Generate n_readings rows distributed across stations."""
    rng = random.Random(seed)
    base_ts = 1704067200  # 2024-01-01T00:00:00Z
    hour_secs = 3600

    rows = []
    # Distribute readings: n_readings/n_stations per station (at least 1 per station)
    n_stations = len(stations)
    readings_per_station = max(1, n_readings // n_stations)

    count = 0
    for h, sid in enumerate(stations):
        for r in range(readings_per_station):
            if count >= n_readings:
                break
            ts_sec = base_ts + r * hour_secs
            ts_str = _sec_to_iso(ts_sec)
            t_val = 25.0 + rng.uniform(-2.0, 2.0)
            rh_val = 55.0 + rng.uniform(-5.0, 5.0)
            p_val = 1010.0 + rng.uniform(-2.0, 2.0)
            td_val = t_val - ((100.0 - rh_val) / 5.0)
            rows.append({
                "station_id": sid,
                "ts_utc": ts_str,
                "T": round(t_val, 2),
                "Td": round(td_val, 2),
                "RH": round(rh_val, 2),
                "P": round(p_val, 2),
                "P_type": "slp",
                "cadence_min": 60,
                "schema_v": "1.0",
                "source": "imd_wis2",
            })
            count += 1
        if count >= n_readings:
            break

    # If we still have fewer than n_readings (edge case with very few stations per reading),
    # top up with the first station
    while len(rows) < n_readings:
        excess_h = len(rows)
        sid = stations[0]
        ts_str = _sec_to_iso(base_ts + excess_h * hour_secs)
        rows.append({
            "station_id": sid,
            "ts_utc": ts_str,
            "T": 25.0, "Td": 15.0, "RH": 55.0, "P": 1010.0,
            "P_type": "slp", "cadence_min": 60,
            "schema_v": "1.0", "source": "imd_wis2",
        })

    return rows[:n_readings]


def _sec_to_iso(ts_sec: int) -> str:
    import datetime
    dt = datetime.datetime.fromtimestamp(ts_sec, tz=datetime.timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def run_pipeline(
    rows: list[dict],
    registry: dict[str, dict],
    neighbours_map: dict[str, list[str]],
    validate_fn,
    rule_gate_fn,
    score_fn,
) -> tuple[float, list[float]]:
    """Run validate + rule_gate + score for all rows.
    Returns (total_seconds, list_of_per_row_ms).
    """
    # Build station windows incrementally
    station_windows: dict[str, list[dict]] = {sid: [] for sid in registry}

    latencies: list[float] = []
    t_start = time.perf_counter()

    for row in rows:
        t0 = time.perf_counter()

        # 1. Validate
        try:
            validated = validate_fn(row)
        except Exception:
            t1 = time.perf_counter()
            latencies.append((t1 - t0) * 1000.0)
            continue

        sid = validated["station_id"]
        station_windows[sid].append(validated)

        # 2. Rule gate
        gate_res = rule_gate_fn(station_windows[sid], cadence_min=60)

        gate_failed = any(
            gate_res.get(v, {}).get("fail", False) for v in ("T", "RH", "P")
        )

        if not gate_failed:
            # 3. Score — include neighbours in window
            window = {sid: station_windows[sid]}
            for nb in neighbours_map.get(sid, [])[:8]:  # limit to 8 neighbours
                if nb in station_windows and station_windows[nb]:
                    window[nb] = station_windows[nb][-3:]  # last 3 readings

            try:
                score_fn(window, sid)
            except Exception:
                pass

        t1 = time.perf_counter()
        latencies.append((t1 - t0) * 1000.0)

    t_end = time.perf_counter()
    return t_end - t_start, latencies


def main():
    root = Path(__file__).resolve().parent.parent.parent
    sys.path.insert(0, str(root))

    from skyguard.contract import validate_input_row
    from skyguard.ingest.rule_gate import check as rule_gate_check
    from skyguard.scorer import score as scorer_score

    os.environ["SKYGUARD_SCORER"] = "fake"

    git_sha = get_git_sha()
    python_ver = platform.python_version()
    cpu = platform.processor() or platform.machine() or "unknown"

    results = {}
    n_readings = TARGET_READINGS
    reduced = False

    # Quick probe: estimate time for 100 stations with 100 readings
    probe_registry = generate_stations(100, seed=99)
    probe_neighbours = compute_neighbours(probe_registry, radius_km=150.0)
    probe_rows = generate_rows(list(probe_registry.keys()), 100)
    probe_t, _ = run_pipeline(
        probe_rows, probe_registry, probe_neighbours,
        validate_input_row, rule_gate_check, scorer_score
    )
    # Extrapolate worst case: 10000 stations * 5000 readings * 3 runs
    # (very rough: scale with stations * readings)
    estimated_total = probe_t / 100 * TARGET_READINGS * 3 * 3  # 3 sizes * 3 runs (approx)
    if estimated_total > MAX_SECONDS:
        n_readings = FALLBACK_READINGS
        reduced = True
        print(f"Reducing to {FALLBACK_READINGS} readings per size (estimated {estimated_total:.0f}s > {MAX_SECONDS}s)")

    for n_stations in SIZES:
        print(f"\n--- Size: {n_stations} stations, {n_readings} readings/run ---")
        registry = generate_stations(n_stations, seed=42)
        station_list = list(registry.keys())

        # Precompute neighbours once per size
        t_nb = time.perf_counter()
        neighbours_map = compute_neighbours(registry, radius_km=150.0)
        t_nb_end = time.perf_counter()
        print(f"  Neighbour precompute: {t_nb_end - t_nb:.2f}s")

        rows = generate_rows(station_list, n_readings, seed=7)

        run_times: list[float] = []
        rps_list: list[float] = []
        p50_list: list[float] = []
        p95_list: list[float] = []
        peak_mb_list: list[float] = []

        for run_i in range(N_RUNS):
            tracemalloc.start()
            total_s, latencies = run_pipeline(
                rows, registry, neighbours_map,
                validate_input_row, rule_gate_check, scorer_score
            )
            _, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()

            latencies.sort()
            n_lat = len(latencies)
            p50 = latencies[int(n_lat * 0.50)] if n_lat else 0.0
            p95 = latencies[int(n_lat * 0.95)] if n_lat else 0.0
            rps = n_readings / total_s if total_s > 0 else 0.0

            run_times.append(total_s)
            rps_list.append(rps)
            p50_list.append(p50)
            p95_list.append(p95)
            peak_mb_list.append(peak / 1024 / 1024)

            print(f"  Run {run_i+1}: {rps:.1f} readings/s, p50={p50:.2f}ms, p95={p95:.2f}ms, "
                  f"peak={peak_mb_list[-1]:.1f}MB")

        results[str(n_stations)] = {
            "n_readings": n_readings,
            "n_stations": n_stations,
            "required_rate_per_sec": round(n_stations / 3600, 4),
            "readings_per_sec_mean": round(sum(rps_list) / N_RUNS, 2),
            "readings_per_sec_min": round(min(rps_list), 2),
            "readings_per_sec_max": round(max(rps_list), 2),
            "p50_ms_mean": round(sum(p50_list) / N_RUNS, 3),
            "p95_ms_mean": round(sum(p95_list) / N_RUNS, 3),
            "peak_memory_mb_mean": round(sum(peak_mb_list) / N_RUNS, 2),
            "runs": N_RUNS,
            "cpu": cpu,
            "python": python_ver,
            "scorer": "fake",
            "git_sha": git_sha,
        }
        if reduced:
            results[str(n_stations)]["note"] = (
                f"Reduced from {TARGET_READINGS} to {FALLBACK_READINGS} readings "
                f"(estimated full run >{MAX_SECONDS}s)"
            )

    out_dir = root / "reports" / "scale"
    out_dir.mkdir(parents=True, exist_ok=True)

    results_path = out_dir / "results.json"
    with open(results_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nWrote {results_path}")

    # Generate chart
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        size_keys = [str(s) for s in SIZES]
        stations_arr = [int(k) for k in size_keys]
        rps_arr = [results[k]["readings_per_sec_mean"] for k in size_keys]
        p95_arr = [results[k]["p95_ms_mean"] for k in size_keys]
        req_arr = [results[k]["required_rate_per_sec"] for k in size_keys]

        fig, ax1 = plt.subplots(figsize=(8, 5))
        ax1.plot(stations_arr, rps_arr, "b-o", label="Readings/s (achieved)")
        ax1.plot(stations_arr, req_arr, "g--s", label="Required rate/s (hourly)")
        ax1.set_xlabel("Network size (stations)")
        ax1.set_ylabel("Readings / second", color="b")
        ax1.set_xscale("log")
        ax1.legend(loc="upper left")

        ax2 = ax1.twinx()
        ax2.plot(stations_arr, p95_arr, "r-^", label="p95 latency (ms)")
        ax2.set_ylabel("p95 latency (ms)", color="r")
        ax2.legend(loc="upper right")

        plt.title("SkyGuard Scale Test — validate + rule_gate + scorer (fake)")
        plt.tight_layout()
        png_path = out_dir / "scale.png"
        plt.savefig(png_path, dpi=120)
        plt.close()
        print(f"Wrote {png_path}")
    except ImportError:
        print("matplotlib not available — skipping chart")


if __name__ == "__main__":
    main()
