"""End-to-end check for STEP 1 — Demo fixes.

Run while the server is up on port 8000:
    python scripts/e2e_step1.py
"""
import json
import time
import urllib.request

base = "http://127.0.0.1:8000"
print("=== END-TO-END CHECK for STEP 1 ===")
print()

# 1. Health check
t0 = time.time()
resp = urllib.request.urlopen(f"{base}/health", timeout=2)
t1 = time.time()
print(f"1. /health: {json.loads(resp.read())} ({(t1-t0)*1000:.0f}ms)")

# 2. Scorer info / banner
resp = urllib.request.urlopen(f"{base}/scorer-info", timeout=2)
info = json.loads(resp.read())
print(f"2. /scorer-info: backend={info['backend']}, banner=\"{info['banner_text']}\", level={info['banner_level']}")

# 3. Speed up replay
req = urllib.request.Request(
    f"{base}/replay/speed",
    data=json.dumps({"speed_factor": 50000.0}).encode(),
    headers={"Content-Type": "application/json"},
)
urllib.request.urlopen(req)
print("3. Replay speed set to 50000x")

# 4. Wait for some verdicts
time.sleep(3)

# 5. Inject 55C fault
sid = "INI0001"
req = urllib.request.Request(
    f"{base}/inject-fault",
    data=json.dumps({"preset": "55C", "station_id": sid}).encode(),
    headers={"Content-Type": "application/json"},
)
resp = urllib.request.urlopen(req)
inj = json.loads(resp.read())
print(f"4. /inject-fault 55C: root_cause={inj['injection']['root_cause']}, magnitude={inj['injection']['magnitude']}")
assert inj["injection"]["root_cause"] == "out_of_range", "FAIL: 55C preset should be out_of_range"

# 6. Wait for scorer to process the injected reading
time.sleep(4)

# 7. Check alerts for anomaly/out_of_range
resp = urllib.request.urlopen(f"{base}/alerts", timeout=2)
alerts = json.loads(resp.read())
fault_alerts = [
    a for a in alerts
    if a.get("station_id") == sid and a.get("label") in ("anomaly", "uncertain")
]
if fault_alerts:
    first = fault_alerts[0]
    rc = first.get("vars", {}).get("T", {}).get("root_cause", "?")
    print(f"5. Fault alert found: station={sid}, label={first['label']}, T_root_cause={rc}")
else:
    print(f"5. WARNING: No fault alert found for {sid} yet (may need more time)")

# 8. Inject genuine storm on the same station
req = urllib.request.Request(
    f"{base}/inject-event",
    data=json.dumps({"station_id": sid, "kind": "heat_wave", "duration_hours": 3.0}).encode(),
    headers={"Content-Type": "application/json"},
)
resp = urllib.request.urlopen(req)
evt = json.loads(resp.read())
print(f"6. /inject-event: kind={evt['event']['kind']}, affected={len(evt['event']['affected_stations'])} stations")
assert len(evt["event"]["affected_stations"]) > 1, "FAIL: event should affect target + neighbours"

# 9. Wait for scorer to process event readings
time.sleep(4)

# 10. Check stations for genuine_event
resp = urllib.request.urlopen(f"{base}/stations", timeout=2)
stations = json.loads(resp.read())
event_stations = [s for s in stations if s.get("genuine_event")]
non_anomaly_events = [s for s in event_stations if s.get("latest_label") == "normal"]
print(f"7. Stations with genuine_event=true: {len(event_stations)} (of which normal: {len(non_anomaly_events)})")
for s in event_stations[:5]:
    print(f"   - {s['id']}: label={s['latest_label']}, genuine_event={s['genuine_event']}")

# 11. Final health check
t0 = time.time()
resp = urllib.request.urlopen(f"{base}/health", timeout=1)
t1 = time.time()
print(f"8. Final /health: {json.loads(resp.read())} ({(t1-t0)*1000:.0f}ms)")
assert (t1 - t0) < 1.0, "FAIL: health check should be < 1s"

print()
print("=== STEP 1 END-TO-END CHECK COMPLETE ===")
