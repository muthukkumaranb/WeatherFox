import time
import urllib.request
import json

base = "http://127.0.0.1:8000"
print("=== REAL-SERVER PACING CHECK (sampling /stations every 2s for 10s at default 1800x speed) ===")
print()

for i in range(5):
    time.sleep(2.0)
    try:
        res = urllib.request.urlopen(f"{base}/stations", timeout=2)
        st = json.loads(res.read())
        ts = st[0]["latest_ts"] if st else "N/A"
        sid = st[0]["id"] if st else "N/A"
        print(f"Sample {i+1} (t={(i+1)*2}s real): station={sid}, latest_ts={ts}")
    except Exception as e:
        print(f"Sample {i+1}: error {e}")
