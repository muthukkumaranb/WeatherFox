"""scripts/eval_val.py — evaluate on the VAL split only.

Runs the real scorer on val rows with injected faults, computes:
  - recall by root cause × variable
  - false alarm rate on clean rows
  - confusion matrix
Writes reports/val/report.json.
"""
import json
import logging
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DATA_DIR    = Path("data")
SPLITS_DIR  = Path("splits")
REPORTS_DIR = Path("reports") / "val"


def evaluate_val():
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    # ── Load val_eval split (clean) ───────────────────────────────────────────────
    val_path = SPLITS_DIR / "val_eval.jsonl"
    if not val_path.exists():
        logger.error("val_eval.jsonl not found")
        return
    clean_rows = []
    import math
    with open(val_path, encoding="utf-8") as fh:
        for line in fh:
            r = json.loads(line)
            r.pop("lat", None)
            r.pop("lon", None)
            r.pop("name", None)
            for k, v in list(r.items()):
                if isinstance(v, float) and math.isnan(v):
                    r[k] = None
            clean_rows.append(r)

    # ── Load injected val + labels ───────────────────────────────────────────
    inj_parquet = DATA_DIR / "stream" / "injected_val_eval.parquet"
    labels_path = DATA_DIR / "labels" / "injections_val_eval.jsonl"

    has_injections = inj_parquet.exists() and labels_path.exists()
    labels: list[dict] = []
    if has_injections:
        import pandas as pd
        df_inj = pd.read_parquet(inj_parquet)
        inj_rows = df_inj.to_dict("records")
        # nan → None
        import math
        for r in inj_rows:
            r.pop("lat", None)
            r.pop("lon", None)
            r.pop("name", None)
            for k, v in r.items():
                if isinstance(v, float) and math.isnan(v):
                    r[k] = None
        with open(labels_path, encoding="utf-8") as fh:
            for line in fh:
                labels.append(json.loads(line))
        logger.info(f"Loaded {len(inj_rows):,} injected val rows, {len(labels)} fault labels")
    else:
        inj_rows = clean_rows
        logger.warning("No injected val data found — evaluating on clean rows only")

    # Build label index: (station_id, ts_utc) → label dict
    label_idx: dict[tuple[str, str], dict] = {}
    import datetime
    for lbl in labels:
        sid = lbl["station_id"]
        start_ts = lbl["start_ts"]
        end_ts = lbl["end_ts"]
        
        # We need to map all timestamps in the range to this label
        dt = datetime.datetime.strptime(start_ts, "%Y-%m-%dT%H:%M:%SZ")
        end_dt = datetime.datetime.strptime(end_ts, "%Y-%m-%dT%H:%M:%SZ")
        while dt <= end_dt:
            ts = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            label_idx[(sid, ts)] = lbl
            dt += datetime.timedelta(minutes=30) # approximate, but will cover hourly and half-hourly

    # ── Score val rows ───────────────────────────────────────────────────────
    import os
    os.environ["SKYGUARD_SCORER"] = "real"
    from skyguard.data.registry import load_registry, neighbours
    registry = load_registry(str(Path("data/station_registry.csv")))
    inj_rows.sort(key=lambda x: x["ts_utc"])
    
    t0 = time.perf_counter()
    from skyguard.verdict.batch import score_all_batch
    all_verdicts = score_all_batch(inj_rows)
    
    verdicts: list[dict] = []
    
    # eval_val.py originally appended _station_id and _ts_utc to verdicts. 
    # Also filtered out rows with no history. score_all_batch returns verdicts for rows with history (since we need it to score).
    for v in all_verdicts:
        sid = v["station_id"]
        v_ts = v["ts_utc"]
        v["_station_id"] = sid
        v["_ts_utc"] = v_ts
        verdicts.append(v)
        
    n_scored = len(verdicts)
    logger.info(f"  scored {n_scored} rows …")
    elapsed = time.perf_counter() - t0

    # ── Save verdicts for offline re-analysis ────────────────────────────
    verdicts_path = REPORTS_DIR / "verdicts.jsonl"
    with open(verdicts_path, "w", encoding="utf-8") as fh:
        for v in verdicts:
            fh.write(json.dumps(v) + "\n")
    logger.info(f"Saved {len(verdicts):,} verdicts to {verdicts_path}")
    
    labels_out_path = REPORTS_DIR / "labels.jsonl"
    with open(labels_out_path, "w", encoding="utf-8") as fh:
        for lbl in labels:
            fh.write(json.dumps(lbl) + "\n")
    logger.info(f"Saved {len(labels)} labels to {labels_out_path}")

    # ── Compute metrics ──────────────────────────────────────────────────────
    # 1) Count labels by verdict label
    label_counts = Counter(v["label"] for v in verdicts)

    # 2) False alarm rate on clean rows
    # Build interval index: for each station, sorted list of (start_ts, end_ts) injection windows
    from bisect import bisect_right
    inj_intervals: dict[str, list[tuple[str, str]]] = {}
    for lbl in labels:
        sid = lbl["station_id"]
        inj_intervals.setdefault(sid, []).append((lbl["start_ts"], lbl["end_ts"]))
    for sid in inj_intervals:
        inj_intervals[sid].sort()
    # Build sorted start_ts lists for binary search
    inj_starts: dict[str, list[str]] = {sid: [iv[0] for iv in ivs] for sid, ivs in inj_intervals.items()}

    def _is_injected(sid: str, ts: str) -> bool:
        """Check if (sid, ts) falls within any injection [start_ts, end_ts]."""
        ivs = inj_intervals.get(sid)
        if not ivs:
            return False
        starts = inj_starts[sid]
        # Find rightmost interval whose start_ts <= ts
        idx = bisect_right(starts, ts) - 1
        if idx >= 0 and ivs[idx][0] <= ts <= ivs[idx][1]:
            return True
        # Also check idx+1 in case of equal start
        if idx + 1 < len(ivs) and ivs[idx + 1][0] <= ts <= ivs[idx + 1][1]:
            return True
        return False

    n_clean_scored = 0
    n_false_alarm  = 0
    for v in verdicts:
        sid = v.get("_station_id", v.get("station_id"))
        ts  = v.get("_ts_utc", v.get("ts_utc"))
        if not _is_injected(sid, ts):
            n_clean_scored += 1
            if v["label"] in ("anomaly", "uncertain"):
                n_false_alarm += 1

    fa_rate = n_false_alarm / max(n_clean_scored, 1)

    # 3) Recall by root cause: did ANY verdict in the injection window get flagged?
    # Index verdicts by station for fast lookup
    verdicts_by_station: dict[str, list[dict]] = {}
    for v in verdicts:
        sid = v.get("_station_id", v.get("station_id"))
        verdicts_by_station.setdefault(sid, []).append(v)
    for sid in verdicts_by_station:
        verdicts_by_station[sid].sort(key=lambda v: v.get("_ts_utc", v.get("ts_utc", "")))

    recall_by_cause: dict[str, dict] = {}
    for lbl in labels:
        cause = lbl["root_cause"]
        sid   = lbl["station_id"]
        start = lbl["start_ts"]
        end   = lbl["end_ts"]

        detected = False
        for v in verdicts_by_station.get(sid, []):
            vts = v.get("_ts_utc", v.get("ts_utc", ""))
            if vts < start:
                continue
            if vts > end:
                break
            if v["label"] in ("anomaly", "uncertain"):
                detected = True
                break

        if cause not in recall_by_cause:
            recall_by_cause[cause] = {"detected": 0, "total": 0}
        recall_by_cause[cause]["total"] += 1
        if detected:
            recall_by_cause[cause]["detected"] += 1

    # ── Build report ─────────────────────────────────────────────────────────
    report = {
        "total_verdicts": len(verdicts),
        "label_counts": dict(label_counts),
        "false_alarm_rate": round(fa_rate, 4),
        "false_alarms": n_false_alarm,
        "clean_scored": n_clean_scored,
        "recall_by_root_cause": {},
        "scoring_time_s": round(elapsed, 1),
        "latency_ms_per_row": round(elapsed * 1000 / max(n_scored, 1), 2),
    }
    for cause, d in sorted(recall_by_cause.items()):
        rec = d["detected"] / max(d["total"], 1)
        report["recall_by_root_cause"][cause] = {
            "detected": d["detected"], "total": d["total"], "recall": round(rec, 3)
        }

    with open(REPORTS_DIR / "report.json", "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)

    metrics_text = [
        "============================================================",
        "  eval_val.py — SUMMARY (VAL split)",
        "============================================================",
        f"  Verdicts scored    : {len(verdicts):,}",
        f"  Label distribution : {dict(label_counts)}",
        f"  False-alarm rate   : {fa_rate:.4f}  ({n_false_alarm}/{n_clean_scored})",
        f"  Scoring time       : {elapsed:.1f} s  ({elapsed*1000/max(n_scored,1):.2f} ms/row)",
        "",
        f"  {'Root cause':20s}  {'Detected':>8s}  {'Total':>5s}  {'Recall':>7s}",
        f"  {'-'*20}  {'-'*8}  {'-'*5}  {'-'*7}"
    ]
    for cause, d in sorted(recall_by_cause.items()):
        rec = d["detected"] / max(d["total"], 1)
        metrics_text.append(f"  {cause:20s}  {d['detected']:8d}  {d['total']:5d}  {rec:7.3f}")
    metrics_text.append("============================================================")
    
    with open(REPORTS_DIR / "metrics.md", "w", encoding="utf-8") as fh:
        fh.write("\n".join(metrics_text) + "\n")

    # ── Summary ──────────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("  eval_val.py — SUMMARY (VAL split)")
    print("=" * 60)
    print(f"  Verdicts scored    : {len(verdicts):,}")
    print(f"  Label distribution : {dict(label_counts)}")
    print(f"  False-alarm rate   : {fa_rate:.4f}  ({n_false_alarm}/{n_clean_scored})")
    print(f"  Scoring time       : {elapsed:.1f} s  ({elapsed*1000/max(n_scored,1):.2f} ms/row)")
    print()
    print(f"  {'Root cause':20s}  {'Detected':>8s}  {'Total':>5s}  {'Recall':>7s}")
    print(f"  {'-'*20}  {'-'*8}  {'-'*5}  {'-'*7}")
    for cause, d in sorted(recall_by_cause.items()):
        rec = d["detected"] / max(d["total"], 1)
        print(f"  {cause:20s}  {d['detected']:8d}  {d['total']:5d}  {rec:7.3f}")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    evaluate_val()
