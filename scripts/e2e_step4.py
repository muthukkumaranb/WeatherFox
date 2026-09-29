"""End-to-end check script for STEP 4 — One-Command Demo.

Runs while the server is up on port 8000:
    python scripts/e2e_step4.py
"""
from __future__ import annotations

import json
import time
import urllib.request


def run_e2e_step4() -> None:
    base = "http://127.0.0.1:8000"
    print("=== END-TO-END CHECK FOR STEP 4 ===")
    print()

    # 1. GET /health
    resp = urllib.request.urlopen(f"{base}/health", timeout=5)
    health = json.loads(resp.read())
    print(f"1. /health: {health}")

    # 2. GET /stations count
    resp = urllib.request.urlopen(f"{base}/stations", timeout=5)
    stations = json.loads(resp.read())
    print(f"2. /stations count: {len(stations)}")

    # 3. GET /alerts (at least one alert)
    resp = urllib.request.urlopen(f"{base}/alerts", timeout=5)
    alerts = json.loads(resp.read())
    print(f"3. /alerts count: {len(alerts)}")
    if alerts:
        print(f"   Sample Alert: station={alerts[0].get('station_id')}, label={alerts[0].get('label')}, ts={alerts[0].get('ts_utc')}")

    print()
    print("=== STEP 4 END-TO-END CHECK COMPLETE ===")


if __name__ == "__main__":
    run_e2e_step4()
