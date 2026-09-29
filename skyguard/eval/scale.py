import os
import sys
import time
import json
import random
import platform
import tracemalloc
import subprocess
from pathlib import Path
import matplotlib.pyplot as plt

def generate_network(n_stations):
    return [f"s{i}" for i in range(n_stations)]

def generate_rows(stations, n_hours=24):
    rows = []
    for h in range(n_hours):
        ts = f"2024-01-01T{h:02d}:00:00Z"
        for s in stations:
            rows.append({
                "station_id": s,
                "ts_utc": ts,
                "T": 25.0 + random.random(),
                "Td": 20.0 + random.random(),
                "RH": 50.0,
                "P": 1010.0,
                "P_type": "slp",
                "cadence_min": 60,
                "schema_v": "1.0",
                "source": "esp32"
            })
    return rows

def get_git_sha():
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    except:
        return "unknown"

def main():
    root = Path(__file__).resolve().parent.parent.parent
    sys.path.insert(0, str(root))
    
    from skyguard.ingest.rule_gate import check
    from skyguard.scorer import score
    from skyguard.contract import validate_input_row
    
    os.environ["SKYGUARD_SCORER"] = "fake"
    
    sizes = [100, 1000, 10000]
    results = {}
    
    for n_stations in sizes:
        stations = generate_network(n_stations)
        rows = generate_rows(stations, 24)
        
        runs = 3
        readings_per_sec_list = []
        p50_list = []
        p95_list = []
        peak_mb_list = []
        
        for run in range(runs):
            tracemalloc.start()
            latencies = []
            
            t_start = time.perf_counter()
            for row in rows:
                t0 = time.perf_counter()
                
                valid = validate_input_row(row)
                res = score({row["station_id"]: [row]}, row["station_id"])
                
                t1 = time.perf_counter()
                latencies.append((t1 - t0) * 1000)
                
            t_end = time.perf_counter()
            current, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            
            total_time = t_end - t_start
            readings_per_sec = len(rows) / total_time
            latencies.sort()
            
            p50 = latencies[int(len(latencies)*0.5)]
            p95 = latencies[int(len(latencies)*0.95)]
            
            readings_per_sec_list.append(readings_per_sec)
            p50_list.append(p50)
            p95_list.append(p95)
            peak_mb_list.append(peak / 1024 / 1024)
            
        results[str(n_stations)] = {
            "readings_per_sec_mean": sum(readings_per_sec_list) / runs,
            "p50_ms_mean": sum(p50_list) / runs,
            "p95_ms_mean": sum(p95_list) / runs,
            "peak_memory_mb_mean": sum(peak_mb_list) / runs,
            "runs": runs,
            "cpu": platform.processor(),
            "python": platform.python_version(),
            "scorer": "fake",
            "git_sha": get_git_sha()
        }
        
    out_dir = root / "reports" / "scale"
    out_dir.mkdir(parents=True, exist_ok=True)
    
    with open(out_dir / "results.json", "w") as f:
        json.dump(results, f, indent=2)
        
    # plot
    stations_arr = [int(k) for k in results.keys()]
    tps = [results[k]["readings_per_sec_mean"] for k in results.keys()]
    p95 = [results[k]["p95_ms_mean"] for k in results.keys()]
    
    fig, ax1 = plt.subplots()
    ax1.plot(stations_arr, tps, 'b-')
    ax1.set_xlabel('Stations')
    ax1.set_ylabel('Readings / s', color='b')
    
    ax2 = ax1.twinx()
    ax2.plot(stations_arr, p95, 'r-')
    ax2.set_ylabel('p95 latency (ms)', color='r')
    
    plt.savefig(out_dir / "scale.png")
    print(f"Wrote {out_dir}/results.json and scale.png")

if __name__ == "__main__":
    main()
