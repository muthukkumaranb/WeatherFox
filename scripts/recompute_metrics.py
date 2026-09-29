"""Recompute eval metrics from the already-scored verdicts.

Since eval_val.py takes ~80 min to re-score, this script loads the
saved verdicts from the report and the injection labels, then
recomputes FAR and recall with the corrected interval-overlap logic.
"""
import json
import logging
from bisect import bisect_right
from collections import Counter
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DATA_DIR    = Path("data")
REPORTS_DIR = Path("reports") / "val"


def recompute():
    # ── Load labels ──────────────────────────────────────────────────────
    labels_path = DATA_DIR / "labels" / "injections_val.jsonl"
    labels = []
    with open(labels_path, encoding="utf-8") as fh:
        for line in fh:
            labels.append(json.loads(line))
    logger.info(f"Loaded {len(labels)} injection labels")

    # ── Load verdicts ────────────────────────────────────────────────────
    verdicts_path = REPORTS_DIR / "verdicts.jsonl"
    if not verdicts_path.exists():
        logger.error("verdicts.jsonl not found — need to save verdicts during eval_val.py")
        logger.info("Attempting to re-run eval_val.py with verdict saving...")
        return

    verdicts = []
    with open(verdicts_path, encoding="utf-8") as fh:
        for line in fh:
            verdicts.append(json.loads(line))
    logger.info(f"Loaded {len(verdicts):,} verdicts")

    # ── Compute metrics with interval overlap ────────────────────────────
    label_counts = Counter(v["label"] for v in verdicts)

    # Build interval index
    inj_intervals: dict[str, list[tuple[str, str]]] = {}
    for lbl in labels:
        sid = lbl["station_id"]
        inj_intervals.setdefault(sid, []).append((lbl["start_ts"], lbl["end_ts"]))
    for sid in inj_intervals:
        inj_intervals[sid].sort()
    inj_starts: dict[str, list[str]] = {
        sid: [iv[0] for iv in ivs] for sid, ivs in inj_intervals.items()
    }

    def _is_injected(sid: str, ts: str) -> bool:
        ivs = inj_intervals.get(sid)
        if not ivs:
            return False
        starts = inj_starts[sid]
        idx = bisect_right(starts, ts) - 1
        if idx >= 0 and ivs[idx][0] <= ts <= ivs[idx][1]:
            return True
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

    # Recall by root cause (interval overlap)
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

    # ── Summary ──────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("  RECOMPUTED METRICS (interval overlap)")
    print("=" * 60)
    print(f"  Verdicts           : {len(verdicts):,}")
    print(f"  Label distribution : {dict(label_counts)}")
    print(f"  False-alarm rate   : {fa_rate:.4f}  ({n_false_alarm}/{n_clean_scored})")
    print()
    print(f"  {'Root cause':20s}  {'Detected':>8s}  {'Total':>5s}  {'Recall':>7s}")
    print(f"  {'-'*20}  {'-'*8}  {'-'*5}  {'-'*7}")
    for cause, d in sorted(recall_by_cause.items()):
        rec = d["detected"] / max(d["total"], 1)
        print(f"  {cause:20s}  {d['detected']:8d}  {d['total']:5d}  {rec:7.3f}")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    recompute()
