import json
import time
import subprocess
import urllib.request
import sys
from datetime import datetime

BASE_URL = "http://127.0.0.1:8000"

def get_json(url):
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode())

def post_json(url, data):
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode())

def main():
    print("--- Starting uvicorn server ---")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "skyguard.api.main:create_app", "--factory", "--host", "127.0.0.1", "--port", "8000"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    
    # Wait for server startup
    time.sleep(3)
    
    try:
        # Set speed factor to 1800.0 (30 simulated minutes per real second)
        post_json(f"{BASE_URL}/replay/speed", {"speed_factor": 1800.0})
        print("Replay speed factor set to 1800.0")

        print("Waiting 60s for initial synthetic replay window...")
        time.sleep(60)

        # Speed up slightly for event phase: 3600.0 (1 simulated hour per real second)
        post_json(f"{BASE_URL}/replay/speed", {"speed_factor": 3600.0})

        print("\n--- Injecting Weather Event and Sensor Faults ---")
        # 1. Storm on INI0007 (12 h)
        r_evt = post_json(f"{BASE_URL}/inject-event", {"station_id": "INI0007", "kind": "squall", "duration_hours": 12.0})
        print("Injected storm on INI0007:", r_evt)

        # 2. 55C on INI0001
        r_f1 = post_json(f"{BASE_URL}/inject-fault", {"preset": "55C", "station_id": "INI0001"})
        print("Injected 55C on INI0001:", r_f1)

        # 3. Frozen 24 h on INI0011
        r_f2 = post_json(f"{BASE_URL}/inject-fault", {"station_id": "INI0011", "variable": "T", "root_cause": "frozen", "magnitude": 0.0, "duration_hours": 24.0})
        print("Injected frozen on INI0011:", r_f2)

        # 4. Offset +6 24 h on INI0010
        r_f3 = post_json(f"{BASE_URL}/inject-fault", {"station_id": "INI0010", "variable": "T", "root_cause": "offset", "magnitude": 6.0, "duration_hours": 24.0})
        print("Injected offset on INI0010:", r_f3)

        # 5. Spike +12 on INI0005
        r_f4 = post_json(f"{BASE_URL}/inject-fault", {"station_id": "INI0005", "variable": "T", "root_cause": "spike", "magnitude": 12.0, "duration_hours": 1.0})
        print("Injected spike on INI0005:", r_f4)

        time.sleep(2)  # Wait for a couple replay steps to process injection

        print("\n=== OUTPUT 1: /stations during the storm ===")
        stations = get_json(f"{BASE_URL}/stations")
        for st in stations:
            print(f"Station ID: {st['id']:7s} | Name: {st['name']:15s} | Status: {st['status']:10s} | Genuine Event: {st['genuine_event']}")

        print("\nWaiting for 3 simulated days to complete (approx 50s at speed_factor 3600)...")
        time.sleep(50)

        print("\n=== OUTPUT 2: Alerts grouped by station/root cause after 3 simulated days ===")
        alerts = get_json(f"{BASE_URL}/alerts")
        grouped = {}
        for a in alerts:
            sid = a.get("station_id")
            # find root cause across vars
            rcs = []
            for v_name, v_data in a.get("vars", {}).items():
                if isinstance(v_data, dict) and v_data.get("root_cause"):
                    rcs.append(v_data["root_cause"])
            rc_str = ",".join(set(rcs)) if rcs else a.get("label", "unknown")
            ts = a.get("ts_utc")
            key = (sid, rc_str)
            if key not in grouped:
                grouped[key] = {"station_id": sid, "root_cause": rc_str, "first_ts": ts, "last_ts": ts, "count": 0}
            grouped[key]["count"] += 1
            if ts < grouped[key]["first_ts"]:
                grouped[key]["first_ts"] = ts
            if ts > grouped[key]["last_ts"]:
                grouped[key]["last_ts"] = ts

        for key, info in sorted(grouped.items()):
            print(f"Station: {info['station_id']:7s} | Root Cause: {info['root_cause']:15s} | First TS: {info['first_ts']} | Last TS: {info['last_ts']} | Alert Count: {info['count']}")

        print("\n=== OUTPUT 3: Day-Night T Range from /stations/{id}/series ===")
        test_stations = ["INI0001", "INI0002", "INI0007"]
        for sid in test_stations:
            ser = get_json(f"{BASE_URL}/stations/{sid}/series?hours=72")
            s_data = ser.get("series", [])
            if s_data:
                t_vals = [r["T"] for r in s_data if r.get("T") is not None]
                min_t = min(t_vals) if t_vals else 0
                max_t = max(t_vals) if t_vals else 0
                print(f"Station {sid} ({state_name_by_id(stations, sid)}): T Min = {min_t:.1f} °C, T Max = {max_t:.1f} °C (Range = {max_t - min_t:.1f} °C)")
                # Print a few sample series entries including 55C spike if present
                injected_entries = [r for r in s_data if r.get("injected") or r.get("T") == 55.0]
                if injected_entries:
                    print(f"  Sample injected reading: {injected_entries[0]}")
                else:
                    print(f"  Sample series reading: {s_data[-1]}")

    finally:
        print("\n--- Stopping uvicorn server ---")
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()

def state_name_by_id(stations, sid):
    for st in stations:
        if st["id"] == sid:
            return st["name"]
    return sid

if __name__ == "__main__":
    main()
