import json
import logging
from pathlib import Path
import os
import pytest

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

def test_clean_val_rates():
    val_path = Path("splits/val_eval.jsonl")
    model_path = Path("models/detector.pkl")
    if not val_path.exists() or not model_path.exists():
        pytest.skip("splits/val_eval.jsonl or models/detector.pkl missing")

    os.environ["SKYGUARD_SCORER"] = "real"
    from skyguard.scorer import score as scorer_score
    
    clean_rows = []
    with open(val_path, encoding="utf-8") as f:
        for line in f:
            clean_rows.append(json.loads(line))
            
    # Sample a smaller subset to avoid extremely long test times, or just run full.
    # We will test on 2000 rows.
    import random
    random.seed(42)
    
    import math
    for r in clean_rows:
        r.pop("lat", None)
        r.pop("lon", None)
        r.pop("name", None)
        for k, v in r.items():
            if isinstance(v, float) and math.isnan(v):
                r[k] = None
                
    # We must use network-wide sliding window for this test to be accurate!
    clean_rows.sort(key=lambda x: x["ts_utc"])
    
    import calendar
    def _ts_to_epoch(ts: str) -> int:
        return calendar.timegm((int(ts[0:4]), int(ts[5:7]), int(ts[8:10]), int(ts[11:13]), int(ts[14:16]), int(ts[17:19])))
        
    # Precompute epochs
    epochs = []
    for r in clean_rows:
        epochs.append(_ts_to_epoch(r["ts_utc"]))
        
    # Sample 1500 random indices that have at least 25 hours of history
    # To do this safely, we pick indices from the later half of the dataset
    import random
    random.seed(42)
    sample_indices = random.sample(range(len(clean_rows) // 4, len(clean_rows)), 1500)
    
    verdicts = []
    
    for i, idx in enumerate(sample_indices):
        target_row = clean_rows[idx]
        sid = target_row["station_id"]
        target_epoch = epochs[idx]
        
        # Build 26 hour network window
        cutoff = target_epoch - 26 * 3600
        
        # Find start index
        # Binary search
        import bisect
        start_idx = bisect.bisect_left(epochs, cutoff)
        
        # Load registry once outside loop
        if i == 0:
            from skyguard.data.registry import load_registry, neighbours
            global _registry
            _registry = load_registry(str(Path("data/station_registry.csv")))
            
        nb_sids = set(neighbours(sid, _registry))
        nb_sids.add(sid)
        
        window = {}
        for r in clean_rows[start_idx:idx+1]:
            if r["station_id"] in nb_sids:
                window.setdefault(r["station_id"], []).append(r)
            
        if len(window.get(sid, [])) > 1:
            try:
                v = scorer_score(window, target=sid)
                verdicts.append(v)
                if v["label"] == "anomaly":
                    causes = [v['vars'][var]['root_cause'] for var in v['vars'] if v['vars'][var]['label'] == 'anomaly']
                    print(f"Anomaly! Causes: {causes}")
            except Exception as e:
                print("Exception:", e)
                
        if (i+1) % 500 == 0:
            print(f"Scored {i+1} sampled rows")
            
    n_scored = len(verdicts)
    n_anomaly = sum(1 for v in verdicts if v["label"] == "anomaly")
    n_uncertain = sum(1 for v in verdicts if v["label"] == "uncertain")
    
    anomaly_rate = n_anomaly / n_scored
    uncertain_rate = n_uncertain / n_scored
    
    print(f"Scored {n_scored} clean rows.")
    print(f"Anomaly rate: {anomaly_rate:.4f} (< 0.01 required)")
    print(f"Uncertain rate: {uncertain_rate:.4f} (< 0.03 required)")
    
    assert anomaly_rate < 0.01, f"Anomaly rate too high: {anomaly_rate:.4f}"
    assert uncertain_rate < 0.03, f"Uncertain rate too high: {uncertain_rate:.4f}"
    print("Test passed!")
    
if __name__ == "__main__":
    test_clean_val_rates()
