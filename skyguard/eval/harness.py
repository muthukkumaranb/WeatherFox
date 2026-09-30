import argparse
import json
from collections import defaultdict
import numpy as np
import sys

def bootstrap_ci(data, num_samples=1000, ci=95):
    if not data:
        return 0.0, 0.0
    data = np.array(data)
    n = len(data)
    samples = np.random.choice(data, (num_samples, n), replace=True)
    means = np.mean(samples, axis=1)
    lower = np.percentile(means, (100 - ci) / 2.0)
    upper = np.percentile(means, 100 - (100 - ci) / 2.0)
    return lower, upper

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--verdicts", required=True)
    parser.add_argument("--labels", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    verdicts = []
    with open(args.verdicts) as f:
        for line in f:
            verdicts.append(json.loads(line))
            
    labels = []
    with open(args.labels) as f:
        for line in f:
            labels.append(json.loads(line))

    genuine_fa = sum(1 for v in verdicts if v.get("spatial_support") == "neighbours_also_deviating" and v["label"] in ("anomaly", "uncertain"))
    
    inj_intervals = defaultdict(list)
    for lbl in labels:
        inj_intervals[lbl["station_id"]].append((lbl["start_ts"], lbl["end_ts"]))
    for sid in inj_intervals:
        inj_intervals[sid].sort()

    def is_injected(sid, ts):
        for start, end in inj_intervals.get(sid, []):
            if start <= ts <= end:
                return True
        return False

    clean_anom_by_station = defaultdict(lambda: {"anom": 0, "total": 0})
    clean_uncert_by_station = defaultdict(lambda: {"uncert": 0, "total": 0})
    
    clean_rows = []
    for v in verdicts:
        sid = v.get("station_id", v.get("_station_id"))
        ts = v.get("ts_utc", v.get("_ts_utc"))
        if not is_injected(sid, ts):
            clean_rows.append(v)
            clean_anom_by_station[sid]["total"] += 1
            clean_uncert_by_station[sid]["total"] += 1
            if v["label"] == "anomaly":
                clean_anom_by_station[sid]["anom"] += 1
            elif v["label"] == "uncertain":
                clean_uncert_by_station[sid]["uncert"] += 1
                
    total_clean = len(clean_rows)
    clean_anomaly = sum(1 for v in clean_rows if v["label"] == "anomaly")
    clean_uncertain = sum(1 for v in clean_rows if v["label"] == "uncertain")
    
    anom_rates = [d["anom"]/d["total"] for d in clean_anom_by_station.values() if d["total"] > 0]
    uncert_rates = [d["uncert"]/d["total"] for d in clean_uncert_by_station.values() if d["total"] > 0]
    
    anom_ci = bootstrap_ci(anom_rates)
    uncert_ci = bootstrap_ci(uncert_rates)
    
    anom_rate = clean_anomaly / total_clean if total_clean > 0 else 0
    uncert_rate = clean_uncertain / total_clean if total_clean > 0 else 0
    
    station_days = total_clean / 96.0
    fa_per_day = (clean_anomaly + clean_uncertain) / station_days if station_days > 0 else 0
    genuine_fa_per_100 = genuine_fa / station_days * 100 if station_days > 0 else 0
    
    total_anom_unc = sum(1 for v in verdicts if v["label"] in ("anomaly", "uncertain"))
    chance_recall = total_anom_unc / len(verdicts) if verdicts else 0
    
    verdicts_by_station = defaultdict(list)
    for v in verdicts:
        sid = v.get("_station_id", v.get("station_id"))
        verdicts_by_station[sid].append(v)
    for sid in verdicts_by_station:
        verdicts_by_station[sid].sort(key=lambda v: v.get("_ts_utc", v.get("ts_utc", "")))
        
    recall_by_cause = defaultdict(lambda: {"detected": 0, "total": 0})
    for lbl in labels:
        cause = lbl["root_cause"]
        sid = lbl["station_id"]
        start = lbl["start_ts"]
        end = lbl["end_ts"]
        
        detected = False
        for v in verdicts_by_station.get(sid, []):
            vts = v.get("_ts_utc", v.get("ts_utc", ""))
            if vts < start: continue
            if vts > end: break
            if v["label"] in ("anomaly", "uncertain"):
                detected = True
                break
        recall_by_cause[cause]["total"] += 1
        if detected:
            recall_by_cause[cause]["detected"] += 1
            
    print(f"Clean Anomaly: {anom_rate*100:.3f}% [95% CI: {anom_ci[0]*100:.3f}% - {anom_ci[1]*100:.3f}%]")
    print(f"Clean Uncertain: {uncert_rate*100:.3f}% [95% CI: {uncert_ci[0]*100:.3f}% - {uncert_ci[1]*100:.3f}%]")
    print(f"Chance Recall: {chance_recall*100:.3f}%")
    for cause, d in sorted(recall_by_cause.items()):
        rec = d["detected"] / max(d["total"], 1)
        print(f"Recall ({cause}): {rec*100:.3f}% (Chance: {chance_recall*100:.3f}%)")
    print(f"Recall at <= 0.05 FA/station-day: N/A (Threshold tuning disabled)")
    print(f"Genuine-event FA per 100 station-days: {genuine_fa_per_100:.3f}")
    
    try:
        with open("reports/val/report.json") as f:
            rep = json.load(f)
        print(f"Total Runtime: {rep.get('scoring_time_s', 0):.1f}s")
        print(f"Latency (p50/p95 ms): {rep.get('latency_ms_per_row', 0):.2f} / {rep.get('latency_ms_per_row', 0):.2f} (approx)")
    except Exception:
        pass

if __name__ == '__main__':
    main()
