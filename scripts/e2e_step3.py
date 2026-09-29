"""End-to-end check script for STEP 3 — Operator feedback & CSV export.

Runs while the server is up on port 8000:
    python scripts/e2e_step3.py
"""
from __future__ import annotations

import json
import time
import urllib.request


def run_e2e_step3() -> None:
    base = "http://127.0.0.1:8000"
    print("=== END-TO-END CHECK for STEP 3 ===")
    print()

    # 1. Health check
    resp = urllib.request.urlopen(f"{base}/health", timeout=5)
    data = json.loads(resp.read())
    print(f"1. /health: {data}")

    # 2. Inject fault to create an alert
    req = urllib.request.Request(
        f"{base}/inject-fault",
        data=json.dumps({"preset": "55C", "station_id": "INI0001"}).encode(),
        headers={"Content-Type": "application/json"},
    )
    resp = urllib.request.urlopen(req, timeout=5)
    inj_res = json.loads(resp.read())
    print(f"2. /inject-fault 55C: {inj_res['message']}")

    time.sleep(2)

    # 3. GET /alerts
    resp = urllib.request.urlopen(f"{base}/alerts", timeout=5)
    alerts = json.loads(resp.read())
    print(f"3. /alerts count: {len(alerts)}")

    alert_id = alerts[0]["alert_id"] if alerts else "INI0001_1"

    # 4. POST /alerts/{id}/ack with state=rejected & reason=genuine_weather
    req = urllib.request.Request(
        f"{base}/alerts/{alert_id}/ack",
        data=json.dumps({
            "state": "rejected",
            "reason": "genuine_weather",
            "note": "E2E test operator confirmed genuine heat wave",
            "by": "e2e_tester",
        }).encode(),
        headers={"Content-Type": "application/json"},
    )
    resp = urllib.request.urlopen(req, timeout=5)
    ack_res = json.loads(resp.read())
    print(f"4. POST /alerts/{alert_id}/ack: state={ack_res['state']}, reason={ack_res['feedback'].get('reason')}")

    # 5. GET /alerts?state=rejected
    resp = urllib.request.urlopen(f"{base}/alerts?state=rejected", timeout=5)
    rejected_alerts = json.loads(resp.read())
    print(f"5. GET /alerts?state=rejected count: {len(rejected_alerts)}")

    # 6. GET /export?station_id=INI0001
    resp = urllib.request.urlopen(f"{base}/export?station_id=INI0001", timeout=5)
    csv_bytes = resp.read()
    csv_str = csv_bytes.decode("utf-8")
    lines = csv_str.strip().split("\n")
    print(f"6. GET /export?station_id=INI0001 CSV lines: {len(lines)}")
    print(f"   Header: {lines[0]}")
    if len(lines) > 1:
        print(f"   Row 1 : {lines[1]}")

    print()
    print("=== STEP 3 END-TO-END CHECK COMPLETE ===")


if __name__ == "__main__":
    run_e2e_step3()
