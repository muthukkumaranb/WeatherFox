"""scripts/train.py — fit Detector on train split, calibrate on val split.

Outputs models/detector.pkl (with embedded calibrator fitted on REAL val residuals).
"""
import json
import logging
import os
import time
from pathlib import Path

import numpy as np

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

SPLITS_DIR = Path("splits")
MODELS_DIR = Path("models")


def _load_jsonl(path: Path) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            rows.append(json.loads(line))
    return rows


def train():
    if not SPLITS_DIR.exists():
        logger.error("splits/ not found — run make_data.py first")
        return

    # ── Load splits ──────────────────────────────────────────────────────────
    logger.info("Loading train split …")
    train_rows = _load_jsonl(SPLITS_DIR / "train.jsonl")
    logger.info(f"  {len(train_rows):,} train rows")

    logger.info("Loading val split …")
    val_rows = _load_jsonl(SPLITS_DIR / "val.jsonl")
    logger.info(f"  {len(val_rows):,} val rows")

    # ── Fit model ────────────────────────────────────────────────────────────
    from skyguard.detect.detector import Detector

    det = Detector()
    t0 = time.perf_counter()

    logger.info("Fitting climatology …")
    det.climatology.fit(train_rows)

    logger.info("Fitting forecaster (LightGBM per variable) …")
    det.forecaster.fit(train_rows, det.climatology)

    logger.info("Fitting neighbour model …")
    det.neighbour_model.fit({"T": [], "Td": [], "P": []})

    # ── Calibrate on REAL val residuals ──────────────────────────────────────
    logger.info("Computing residual scores on val split for conformal calibration …")
    by_station: dict[str, list[dict]] = {}
    for r in val_rows:
        by_station.setdefault(r["station_id"], []).append(r)

    cal_scores: dict[tuple[str, int], list[float]] = {}
    n_done = 0
    for sid, s_rows in by_station.items():
        s_rows.sort(key=lambda x: x["ts_utc"])
        history: list[dict] = []
        feats_list = []
        for r in s_rows:
            feats = det.forecaster.extract_features(r, history, det.climatology)
            feats_list.append(feats)
            history.append(r)
            
        x_mat = []
        for f in feats_list:
            x_mat.append([f.get(k) for k in det.forecaster.feature_names])
        x_mat = np.array(x_mat, dtype=float)
        
        preds_all = {}
        for var, model in det.forecaster.models.items():
            preds_all[var] = {
                "pred": model.predict(x_mat),
                "q05": det.forecaster.q05_models[var].predict(x_mat),
                "q95": det.forecaster.q95_models[var].predict(x_mat)
            }
            
        for i, r in enumerate(s_rows):
            cadence = r.get("cadence_min", 60)
            for var in ("T", "Td", "P"):
                val = r.get(var)
                if val is None:
                    continue
                if var in preds_all:
                    pred = preds_all[var]["pred"][i]
                    q05 = preds_all[var]["q05"][i]
                    q95 = preds_all[var]["q95"][i]
                    sigma = max(0.1, (q95 - q05) / 3.29)
                else:
                    pred = val
                    sigma = 1.0
                score = abs(val - pred) / sigma
                cal_scores.setdefault((var, cadence), []).append(score)
        n_done += 1
        if n_done % 5 == 0:
            logger.info(f"  calibration: {n_done}/{len(by_station)} stations")

    det.calibrator.calibrate(cal_scores)
    train_time = time.perf_counter() - t0

    # ── Save ─────────────────────────────────────────────────────────────────
    import pickle
    MODELS_DIR.mkdir(exist_ok=True)
    pkl_path = MODELS_DIR / "detector.pkl"
    with open(pkl_path, "wb") as fh:
        pickle.dump(det, fh)

    pkl_size = pkl_path.stat().st_size

    # ── Summary ──────────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("  train.py — SUMMARY")
    print("=" * 60)
    print(f"  Training time      : {train_time:.1f} s")
    print(f"  Model file         : {pkl_path}")
    print(f"  Model size         : {pkl_size / 1024 / 1024:.1f} MB")
    print(f"  Calibration buckets: {len(cal_scores)}")
    for k, v in sorted(cal_scores.items()):
        print(f"    {k[0]:3s} cad={k[1]:3d}: {len(v):,} scores, "
              f"median={np.median(v):.3f}, p95={np.percentile(v, 95):.3f}")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    train()
