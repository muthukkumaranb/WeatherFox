"""Script to execute E2E demonstration simulation for 3 simulated days."""
from __future__ import annotations

import json
from collections import defaultdict
from skyguard.fake_score import score
from skyguard.ingest.buffers import BufferPool
from skyguard.ingest.replay import generate_synthetic_stream, build_synthetic_registry, compute_neighbours_for_station

def run_e2e_simulation():
    registry = build_synthetic_registry(num_stations=12)
    buffers = BufferPool(max_rows_per_station=200)

    # Injections parameters:
    # 1. Storm on INI0007 (affects INI0007 and its neighbours including INI0001)
    # 2. 55C on INI0001
    # 3. Frozen on INI0011
    # 4. Offset (+6°C) on INI0010

    # Generate 72 hours (3 simulated days) of synthetic data for 12 stations
    stream = generate_synthetic_stream(num_stations=12, rows_per_station=72, start_ts="2026-09-27T18:00:00Z")
    rows_by_hour = defaultdict(list)
    for r in stream:
        rows_by_hour[r["ts_utc"]].append(r)

    # List of all affected stations by storm on INI0007
    storm_affected = set(["INI0007"] + compute_neighbours_for_station("INI0007", registry))

    alerts = []

    for ts_utc, hour_rows in rows_by_hour.items():
        # Apply fault and event injections for this hour
        for r in hour_rows:
            sid = r["station_id"]

            # 1. Storm on INI0007
            if sid in storm_affected:
                r["is_genuine_event"] = True
                r["T"] = round(r["T"] - 6.0, 1)
                r["RH"] = min(98.0, round(r["RH"] + 10.0, 1))
                r["P"] = round(r["P"] + 3.0, 1)

            # 2. 55C on INI0001
            if sid == "INI0001":
                r["T"] = 55.0

            # 3. Frozen on INI0011
            if sid == "INI0011":
                r["T"] = 30.0

            # 4. Offset (+6°C) on INI0010
            if sid == "INI0010":
                r["T"] = round(r["T"] + 6.0, 1)

            # Push row to buffer pool
            buffers.push(r)

        # Score each station for this hour
        for r in hour_rows:
            target_id = r["station_id"]
            target_window = buffers.window(target_id)
            station_window = {target_id: target_window}

            nb_ids = compute_neighbours_for_station(target_id, registry)
            for nb_id in nb_ids:
                nb_w = buffers.window(nb_id)
                if nb_w:
                    station_window[nb_id] = nb_w

            v = score(station_window, target_id, registry=registry)

            # Check if any variable triggered an anomaly or uncertain alert
            if v["label"] in ("anomaly", "uncertain"):
                for var_name, var_res in v["vars"].items():
                    if var_res["label"] in ("anomaly", "uncertain"):
                        alerts.append({
                            "station_id": target_id,
                            "ts_utc": ts_utc,
                            "variable": var_name,
                            "label": var_res["label"],
                            "root_cause": var_res.get("root_cause", "unknown"),
                            "action": var_res.get("action", ""),
                        })

    # Group alerts by station, variable, root cause
    grouped = defaultdict(list)
    for a in alerts:
        key = (a["station_id"], a["variable"], a["root_cause"], a["label"])
        grouped[key].append(a["ts_utc"])

    print("==========================================================================")
    print(" E2E SIMULATION REPORT — 3 SIMULATED DAYS (72 HOURS)")
    print(" Injections: Storm on INI0007 | 55°C on INI0001 | Frozen on INI0011 | Offset on INI0010")
    print("==========================================================================")
    print(f" Total alert events triggered: {len(alerts)}")
    print("--------------------------------------------------------------------------")
    print(" ALERTS GROUPED BY STATION / VARIABLE / ROOT CAUSE:")
    print("--------------------------------------------------------------------------")

    for (sid, var, rc, lbl), ts_list in sorted(grouped.items()):
        first_ts = ts_list[0]
        last_ts = ts_list[-1]
        count = len(ts_list)
        print(f" Station: {sid:7s} | Var: {var:2s} | Label: {lbl:7s} | Root Cause: {rc:12s} | Count: {count:2d} | Range: {first_ts} to {last_ts}")

    print("==========================================================================")

if __name__ == "__main__":
    run_e2e_simulation()
