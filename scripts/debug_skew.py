import json
from pathlib import Path
from skyguard.detect.detector import Detector
import numpy as np
import os
import calendar

os.environ["SKYGUARD_SCORER"] = "real"
from skyguard.scorer import score as scorer_score

def _fast_epoch(ts: str) -> int:
    return calendar.timegm((int(ts[0:4]), int(ts[5:7]), int(ts[8:10]), int(ts[11:13]), int(ts[14:16]), int(ts[17:19])))

def run():
    det = Detector.load()
    val_rows = []
    with open("splits/val.jsonl", encoding="utf-8") as f:
        for i, line in enumerate(f):
            val_rows.append(json.loads(line))
            
    # Group by station
    by_station = {}
    for r in val_rows:
        by_station.setdefault(r["station_id"], []).append(r)
        
    s_rows = list(by_station.values())[0]
    s_rows.sort(key=lambda x: x["ts_utc"])
    
    print(f"Checking skew on {s_rows[0]['station_id']}")
    
    # Generate train features
    history_train = []
    train_feats_list = []
    for r in s_rows:
        feats = det.forecaster.extract_features(r, history_train, det.climatology)
        train_feats_list.append(feats)
        history_train.append(r)
        
    # Generate serving features (mocking eval_val.py)
    sid = s_rows[0]["station_id"]
    for i in range(1, 201):
        r = s_rows[i]
        f_train = train_feats_list[i]
        
        window_start = max(0, i - 24)
        window = {sid: s_rows[window_start:i+1]}
        target_rows = window[sid]
        
        history_serve = target_rows[:-1]
        f_serve = det.forecaster.extract_features(r, history_serve, det.climatology)
        
        diffs = []
        for k in f_train.keys():
            v_tr = f_train.get(k)
            v_sv = f_serve.get(k)
            if v_tr != v_sv:
                # Handle NaNs
                if v_tr is None and v_sv is None: continue
                if isinstance(v_tr, float) and isinstance(v_sv, float) and np.isnan(v_tr) and np.isnan(v_sv): continue
                diffs.append((k, v_tr, v_sv))
                
        if diffs:
            print(f"Row {i} ({r['ts_utc']}) differences (train vs serve):")
            for k, v_tr, v_sv in diffs:
                print(f"  {k}: {v_tr} != {v_sv}")
                
if __name__ == "__main__":
    run()
