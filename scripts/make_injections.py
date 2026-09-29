"""scripts/make_injections.py — inject synthetic faults into each split.

Reads splits/{train,val,test}.jsonl, injects faults, writes:
  data/stream/injected_{split}.parquet
  data/labels/injections_{split}.jsonl
"""
import json
import logging
from collections import Counter
from pathlib import Path

import pandas as pd
from skyguard.data.inject import inject_faults

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

SPLITS_DIR = Path("splits")
DATA_DIR   = Path("data")


def make_injections():
    if not SPLITS_DIR.exists():
        logger.error("splits/ directory not found — run make_data.py first")
        return

    all_stats: dict[str, dict] = {}

    for split in ("train", "val", "test"):
        src = SPLITS_DIR / f"{split}.jsonl"
        if not src.exists():
            logger.warning(f"  {src} not found, skipping")
            continue

        logger.info(f"=== Injecting faults for {split} ===")
        rows = []
        with open(src, encoding="utf-8") as fh:
            for line in fh:
                rows.append(json.loads(line))

        seed = {"train": 1, "val": 2, "test": 3}[split]
        rate = 0.02  # 2 %

        inj_rows, labels = inject_faults(rows, seed=seed, rate=rate, split=split)

        # Write parquet
        stream_dir = DATA_DIR / "stream"
        stream_dir.mkdir(parents=True, exist_ok=True)
        df = pd.DataFrame(inj_rows)
        df.to_parquet(stream_dir / f"injected_{split}.parquet", index=False)

        # Write labels JSONL
        labels_dir = DATA_DIR / "labels"
        labels_dir.mkdir(parents=True, exist_ok=True)
        with open(labels_dir / f"injections_{split}.jsonl", "w", encoding="utf-8") as fh:
            for lbl in labels:
                fh.write(json.dumps(lbl) + "\n")

        # Stats
        by_cause = Counter(l["root_cause"] for l in labels)
        all_stats[split] = {"rows": len(inj_rows), "labels": len(labels), "by_cause": dict(by_cause)}

    # ── Summary ──────────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("  make_injections.py — SUMMARY")
    print("=" * 60)
    for split, st in all_stats.items():
        print(f"\n  [{split}]  rows={st['rows']:,}  faults={st['labels']}")
        for cause, cnt in sorted(st["by_cause"].items()):
            print(f"    {cause:20s}  {cnt}")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    make_injections()
