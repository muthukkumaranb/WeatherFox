import json
import bisect
from skyguard.scorer import score as scorer_score
from skyguard.data.registry import load_registry, neighbours

def main():
    clean_rows = []
    import math
    with open("splits/val_eval.jsonl") as f:
        for line in f:
            r = json.loads(line)
            r.pop("lat", None)
            r.pop("lon", None)
            r.pop("name", None)
            for k, v in r.items():
                if isinstance(v, float) and math.isnan(v):
                    r[k] = None
            clean_rows.append(r)
            
    import calendar
    def _ts_to_epoch(ts: str) -> int:
        return calendar.timegm((int(ts[0:4]), int(ts[5:7]), int(ts[8:10]), int(ts[11:13]), int(ts[14:16]), int(ts[17:19])))

    clean_rows.sort(key=lambda x: x["ts_utc"])
    epochs = [_ts_to_epoch(r["ts_utc"]) for r in clean_rows]
    _registry = load_registry("data/station_registry.csv")

    import random
    random.seed(42)
    sample_indices = random.sample(range(len(clean_rows) // 4, len(clean_rows)), 200)
    
    import skyguard.verdict.api as api
    api.get_detector()
    orig = api._detector.calibrator.get_labels
    def intercept(score, var, cadence):
        label, p = orig(score, var, cadence)
        if label == "anomaly":
            print(f"ANOMALY! Var {var} Score: {score:.3f}, p={p:.6f}")
        return label, p
    api._detector.calibrator.get_labels = intercept

    import os
    os.environ["SKYGUARD_SCORER"] = "real"

    for idx in sample_indices:
        target_row = clean_rows[idx]
        sid = target_row["station_id"]
        cutoff = epochs[idx] - 26 * 3600
        start_idx = bisect.bisect_left(epochs, cutoff)
        
        nb_sids = set(neighbours(sid, _registry))
        nb_sids.add(sid)
        
        window = {}
        for r in clean_rows[start_idx:idx+1]:
            if r["station_id"] in nb_sids:
                window.setdefault(r["station_id"], []).append(r)
                
        if len(window.get(sid, [])) > 1:
            try:
                v = scorer_score(window, target=sid)
                if v["label"] == "anomaly":
                    causes = [v['vars'][var]['root_cause'] for var in v['vars'] if v['vars'][var]['label'] == 'anomaly']
                    print(f"debug_test.py found Anomaly! Causes: {causes}")
            except Exception as e:
                pass

if __name__ == "__main__":
    main()
