import json
from skyguard.detect.detector import Detector
from skyguard.contract import to_model_input
import calendar
import math

def main():
    clean_rows = []
    with open("splits/val_eval.jsonl") as f:
        for line in f:
            clean_rows.append(json.loads(line))
            
    # train.py uses raw rows, but maybe converts nan? No, json.loads returns float nan.
    # Group by station
    by_station = {}
    for r in clean_rows:
        by_station.setdefault(r["station_id"], []).append(r)
        
    det = Detector.load()
    
    diffs = 0
    checked = 0
    for sid, s_rows in by_station.items():
        s_rows.sort(key=lambda x: x["ts_utc"])
        
        # A. train.py path
        history_train = []
        feats_train = []
        for r in s_rows:
            f = det.forecaster.extract_features(r, history_train, det.climatology)
            feats_train.append(f)
            history_train.append(r)
            
        # B. api.py path
        feats_api = []
        for i, r in enumerate(s_rows):
            # API gets a network window. For simplicity, just build the target station's target_rows
            def _fast_epoch(ts: str) -> int:
                return calendar.timegm((int(ts[0:4]), int(ts[5:7]), int(ts[8:10]), int(ts[11:13]), int(ts[14:16]), int(ts[17:19])))
            
            target_ts = _fast_epoch(r["ts_utc"])
            cutoff = target_ts - 26 * 3600
            
            # API also uses clean_rows, but we can just use s_rows since we only care about target history
            window_rows = [hr for hr in s_rows[:i] if _fast_epoch(hr["ts_utc"]) >= cutoff] + [r]
            
            # to_model_input strips qc
            mod_window = [to_model_input(wr) for wr in window_rows]
            
            r_api = mod_window[-1]
            hist_api = mod_window[:-1]
            
            f = det.forecaster.extract_features(r_api, hist_api, det.climatology)
            feats_api.append(f)
            
        # Compare
        for i in range(len(s_rows)):
            f1 = feats_train[i]
            f2 = feats_api[i]
            checked += 1
            
            for k in f1:
                v1 = f1[k]
                v2 = f2[k]
                if v1 != v2:
                    if isinstance(v1, float) and isinstance(v2, float) and math.isnan(v1) and math.isnan(v2):
                        continue
                    print(f"Row {i} Station {sid} Feature {k} differs: train={v1} api={v2}")
                    diffs += 1
                    if diffs > 50:
                        print("Too many diffs")
                        return

    if diffs == 0:
        print(f"NO DIFFERENCES FOUND in {checked} rows!")
    else:
        print(f"Total differences: {diffs}")

if __name__ == "__main__":
    main()
