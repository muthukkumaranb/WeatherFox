"""Final test — run ONCE on the locked test split with injected faults.

Stage 1 (this script): score every injected test reading with the trained WeatherFox model and write
  reports/final/skyguard/verdicts.jsonl + reports/final/labels.jsonl (streamed, constant memory).
Stage 2 (scripts/final_baselines.py): rules-only, z-score and Isolation Forest arms on the same rows.
Then each arm is scored with skyguard.eval.harness and merged with skyguard.eval.combine.

Refuses to run twice (reports/final/.run_stamp).
"""
import hashlib
import json
import logging
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

FINAL = Path("reports") / "final"
TEST_ROWS = Path("data") / "stream" / "injected_test.parquet"
TEST_LABELS = Path("data") / "labels" / "injections_test.jsonl"


def _git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def final_test() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    FINAL.mkdir(parents=True, exist_ok=True)
    stamp = FINAL / ".run_stamp"
    if stamp.exists():
        logger.error("Final test has already been run (%s). Refusing a second run.", stamp)
        return 1
    for p in (TEST_ROWS, TEST_LABELS, Path("models") / "detector.pkl"):
        if not p.exists() or p.stat().st_size == 0:
            logger.error("Missing or empty input: %s", p)
            return 1

    split = json.load(open("splits/split.json"))
    meta = {
        "git_sha": _git_sha(),
        "split_sha256": split.get("sha256"),
        "test_rows_sha256": _sha256(TEST_ROWS),
        "test_labels_sha256": _sha256(TEST_LABELS),
        "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    stamp.write_text(json.dumps(meta, indent=2))  # written first: a crash still counts as "run"

    df = pd.read_parquet(TEST_ROWS).drop(columns=["lat", "lon"], errors="ignore")
    labels = [json.loads(line) for line in open(TEST_LABELS, encoding="utf-8")]
    logger.info("Test: %s readings, %s stations, %s injected faults", f"{len(df):,}",
                df.station_id.nunique(), f"{len(labels):,}")
    shutil.copy(TEST_LABELS, FINAL / "labels.jsonl")

    from skyguard.verdict.batch import score_all_batch

    out_dir = FINAL / "skyguard"
    out_dir.mkdir(exist_ok=True)
    t0 = time.perf_counter()
    n = score_all_batch(df, out_path=str(out_dir / "verdicts.jsonl"))
    elapsed = time.perf_counter() - t0
    meta.update({
        "n_readings": int(len(df)), "n_stations": int(df.station_id.nunique()),
        "n_fault_events": len(labels), "n_verdicts": int(n),
        "skyguard_runtime_s": round(elapsed, 1), "ms_per_reading": round(1000 * elapsed / max(n, 1), 3),
        "finished_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    })
    stamp.write_text(json.dumps(meta, indent=2))
    logger.info("Scored %s readings in %.0f s (%.2f ms/reading)", f"{n:,}", elapsed, meta["ms_per_reading"])
    return 0


if __name__ == "__main__":
    sys.exit(final_test())
