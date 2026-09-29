import json
import bisect
from pathlib import Path

clean_rows = []
with open("splits/val_eval.jsonl") as f:
    for line in f:
        clean_rows.append(json.loads(line))
        
import calendar
def _ts_to_epoch(ts: str) -> int:
    return calendar.timegm((int(ts[0:4]), int(ts[5:7]), int(ts[8:10]), int(ts[11:13]), int(ts[14:16]), int(ts[17:19])))

epochs = []
for r in clean_rows:
    epochs.append(_ts_to_epoch(r["ts_utc"]))
    
from skyguard.data.registry import load_registry, neighbours
_registry = load_registry("data/station_registry.csv")

import random
random.seed(42)
sample_indices = random.sample(range(len(clean_rows) // 4, len(clean_rows)), 1500)

has_neighbours = 0
for idx in sample_indices:
    target_row = clean_rows[idx]
    sid = target_row["station_id"]
    cutoff = epochs[idx] - 26 * 3600
    start_idx = bisect.bisect_left(epochs, cutoff)
    
    nb_sids = set(neighbours(sid, _registry))
    nb_sids.add(sid)
    
    window = set()
    for r in clean_rows[start_idx:idx+1]:
        if r["station_id"] in nb_sids:
            window.add(r["station_id"])
            
    if len(window) > 1:
        has_neighbours += 1
        
print("Out of 1500 sampled rows, " + str(has_neighbours) + " have neighbours in the window!")
