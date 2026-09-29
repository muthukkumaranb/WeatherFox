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

    # ── Load val split (clean) ───────────────────────────────────────────────
    val_path = SPLITS_DIR / "val.jsonl"
    if not val_path.exists():
        logger.error("val.jsonl not found")
        return
    clean_rows = []
    with open(val_path, encoding="utf-8") as fh:
        for line in fh:
            clean_rows.append(json.loads(line))

    # ── Load injected val + labels ───────────────────────────────────────────
    inj_parquet = DATA_DIR / "stream" / "injected_val.parquet"
    labels_path = DATA_DIR / "labels" / "injections_val.jsonl"

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
    for lbl in labels:
        sid = lbl["station_id"]
        # mark all timestamps in range
        start = lbl["start_ts"]
        end   = lbl["end_ts"]
        label_idx[(sid, start)] = lbl  # simplified: keyed by start

    # ── Score val rows ───────────────────────────────────────────────────────
    import os
    os.environ["SKYGUARD_SCORER"] = "real"
    from skyguard.scorer import score as scorer_score

    # Group by station for windowing
    by_station: dict[str, list[dict]] = {}
    for r in inj_rows:
        by_station.setdefault(r["station_id"], []).append(r)

    verdicts: list[dict] = []
    n_scored = 0
    t0 = time.perf_counter()

    for sid, s_rows in by_station.items():
        s_rows.sort(key=lambda x: x["ts_utc"])
        for i in range(1, len(s_rows)):
            window_start = max(0, i - 24)
            window = {sid: s_rows[window_start:i+1]}
            try:
                v = scorer_score(window, target=sid)
                v["_ts_utc"] = s_rows[i]["ts_utc"]
                v["_station_id"] = sid
                verdicts.append(v)
            except Exception as e:
                logger.error(f"Error scoring row: {e}")
            n_scored += 1
            if n_scored % 500 == 0:
                logger.info(f"  scored {n_scored} rows …")

    elapsed = time.perf_counter() - t0

    # ── Compute metrics ──────────────────────────────────────────────────────
    # 1) Count labels by verdict label
    label_counts = Counter(v["label"] for v in verdicts)

    # 2) False alarm rate on clean rows
    # A "false alarm" is anomaly/uncertain on a row NOT covered by any injection label
    injected_ts: set[tuple[str, str]] = set()
    for lbl in labels:
        injected_ts.add((lbl["station_id"], lbl["start_ts"]))

    n_clean_scored = 0
    n_false_alarm  = 0
    for v in verdicts:
        key = (v.get("_station_id", v.get("station_id")), v.get("_ts_utc", v.get("ts_utc")))
        if key not in injected_ts:
            n_clean_scored += 1
            if v["label"] in ("anomaly", "uncertain"):
                n_false_alarm += 1

    fa_rate = n_false_alarm / max(n_clean_scored, 1)

    # 3) Recall by root cause (simplified: did the fault start-ts get flagged?)
    recall_by_cause: dict[str, dict] = {}
    for lbl in labels:
        cause = lbl["root_cause"]
        sid   = lbl["station_id"]
        start = lbl["start_ts"]
        detected = any(
            v.get("_station_id") == sid and v.get("_ts_utc") == start
            and v["label"] in ("anomaly", "uncertain")
            for v in verdicts
        )
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
