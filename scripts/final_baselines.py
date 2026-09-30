"""Final test, stage 2: the three baseline arms on the SAME injected test rows as the model.

Uses Person B's baseline implementations unchanged (skyguard.eval.baselines), fitted on the TRAIN split
only, applied station by station so memory stays bounded. Writes reports/final/<arm>/verdicts.jsonl.
Missing values are given the defaults B's feature code already intends (25 °C / 60 % / 1013 hPa)
only where a key is present with a None/NaN value, which would otherwise crash the arithmetic.
"""
import json
import logging
import math
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

from skyguard.eval import baselines as B

logger = logging.getLogger(__name__)
FINAL = Path("reports") / "final"
DEFAULTS = {"T": 25.0, "RH": 60.0, "P": 1013.0}


def _clean(r: dict) -> dict:
    return {k: (None if isinstance(v, float) and math.isnan(v) else v) for k, v in r.items()}


def _with_defaults(r: dict) -> dict:
    out = dict(r)
    for k, d in DEFAULTS.items():
        if out.get(k) is None:
            out[k] = d
    return out


def _load_jsonl_by_station(path: Path) -> dict[str, list[dict]]:
    by = defaultdict(list)
    keep = ("station_id", "ts_utc", "T", "Td", "RH", "P", "cadence_min", "source")
    with open(path, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            by[r["station_id"]].append({k: r.get(k) for k in keep})
    return by


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    df = pd.read_parquet("data/stream/injected_test.parquet").drop(columns=["lat", "lon", "qc"], errors="ignore")
    test_by = {sid: [_clean(r) for r in g.sort_values("ts_utc").to_dict("records")]
               for sid, g in df.groupby("station_id")}
    del df
    logger.info("Test stations: %d", len(test_by))
    train_by = _load_jsonl_by_station(Path("splits/train.jsonl"))
    logger.info("Train stations: %d, rows: %s", len(train_by), f"{sum(map(len, train_by.values())):,}")

    # Isolation Forest fitted once on TRAIN features (B's feature code and model settings).
    from sklearn.ensemble import IsolationForest
    train_feats = []
    for rows in train_by.values():
        f, _ = B._extract_features([_with_defaults(r) for r in rows])
        train_feats.extend(f)
    iforest = IsolationForest(contamination=0.05, random_state=42)
    iforest.fit(np.nan_to_num(np.array(train_feats, dtype=np.float32)))
    del train_feats
    logger.info("Isolation Forest fitted on train features")

    outs = {arm: open((FINAL / arm).mkdir(parents=True, exist_ok=True) or FINAL / arm / "verdicts.jsonl", "w")
            for arm in ("rules_only", "zscore", "isolation_forest")}
    t0 = time.perf_counter()
    for k, (sid, rows) in enumerate(test_by.items()):
        for v in B.rules_baseline(rows):
            outs["rules_only"].write(json.dumps(v) + "\n")
        for v in B.zscore_baseline(rows, train_rows=train_by.get(sid, [])):
            outs["zscore"].write(json.dumps(v) + "\n")
        feats, ordered = B._extract_features([_with_defaults(r) for r in rows])
        X = np.nan_to_num(np.array(feats, dtype=np.float32))
        preds = iforest.predict(X)
        scores = -iforest.decision_function(X)
        for r, p, sc in zip(ordered, preds, scores):
            is_anom = bool(p == -1)
            var_results = {
                "T": {"label": "anomaly" if is_anom else "normal", "root_cause": "unknown" if is_anom else None, "prob": float(sc)},
                "RH": {"label": "normal", "root_cause": None, "prob": 0.0},
                "P": {"label": "normal", "root_cause": None, "prob": 0.0},
            }
            v = B._make_verdict_record(r["station_id"], r["ts_utc"], "anomaly" if is_anom else "normal",
                                       var_results, model_version="baseline_iforest")
            outs["isolation_forest"].write(json.dumps(v) + "\n")
        if (k + 1) % 25 == 0:
            logger.info("baselines: %d/%d stations (%.0f s)", k + 1, len(test_by), time.perf_counter() - t0)
    for f in outs.values():
        f.close()
    logger.info("Baselines done in %.0f s", time.perf_counter() - t0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
