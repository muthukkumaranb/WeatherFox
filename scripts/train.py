import json
import logging
import os
import time
from pathlib import Path
import numpy as np
import calendar
import math
from skyguard.data.registry import load_registry, get_neighbour_distance

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

def _fast_epoch(ts: str) -> int:
    return calendar.timegm((int(ts[0:4]), int(ts[5:7]), int(ts[8:10]), int(ts[11:13]), int(ts[14:16]), int(ts[17:19])))

def train():
    if not SPLITS_DIR.exists():
        logger.error("splits/ not found")
        return

    logger.info("Loading splits …")
    train_rows = _load_jsonl(SPLITS_DIR / "train.jsonl")
    val_cal_rows = _load_jsonl(SPLITS_DIR / "val_cal.jsonl")
    val_eval_rows = _load_jsonl(SPLITS_DIR / "val_eval.jsonl")
    test_rows = _load_jsonl(SPLITS_DIR / "test.jsonl")
    
    all_rows = train_rows + val_cal_rows + val_eval_rows + test_rows
    
    # Strip NaNs
    for r in all_rows:
        r.pop("lat", None)
        r.pop("lon", None)
        r.pop("name", None)
        for k, v in list(r.items()):
            if isinstance(v, float) and math.isnan(v):
                r[k] = None

    logger.info("Loading registry …")
    registry = load_registry(str(Path("data/station_registry.csv")))

    from skyguard.detect.detector import Detector
    from skyguard.detect.detector import get_rh, get_rh_sigma
    det = Detector()
    t0 = time.perf_counter()

    logger.info("Fitting climatology …")
    det.climatology.fit(train_rows)

    logger.info("Fitting forecaster …")
    det.forecaster.fit(train_rows, det.climatology)

    logger.info("Computing residuals for entire network …")
    by_station = {}
    for r in all_rows:
        by_station.setdefault(r["station_id"], []).append(r)
        
    net_resids = {} # (sid, epoch) -> {var: f_resid, var_sigma: sigma}
    
    for sid, s_rows in by_station.items():
        s_rows.sort(key=lambda x: x["ts_utc"])
        history = []
        feats_list = []
        for r in s_rows:
            feats = det.forecaster.extract_features(r, history, det.climatology)
            feats_list.append(feats)
            history.append(r)
            
        x_mat = np.array([[f.get(k) for k in det.forecaster.feature_names] for f in feats_list], dtype=float)
        
        preds_all = {}
        for var, model in det.forecaster.models.items():
            preds_all[var] = {
                "pred": model.predict(x_mat),
                "q05": det.forecaster.q05_models[var].predict(x_mat),
                "q95": det.forecaster.q95_models[var].predict(x_mat)
            }
            
        for i, r in enumerate(s_rows):
            epoch = _fast_epoch(r["ts_utc"])
            rd = {}
            for var in ("T", "RH", "P"):
                val = r.get(var)
                if val is None:
                    continue
                if var == "RH":
                    if "T" in preds_all and "Td" in preds_all:
                        t_p = preds_all["T"]["pred"][i]
                        td_p = preds_all["Td"]["pred"][i]
                        t_s = max((preds_all["T"]["q95"][i] - preds_all["T"]["q05"][i]) / 3.29, 0.1)
                        td_s = max((preds_all["Td"]["q95"][i] - preds_all["Td"]["q05"][i]) / 3.29, 0.1)
                        pred = get_rh(t_p, td_p)
                        sigma = max(get_rh_sigma(t_p, td_p, t_s, td_s), 0.1)
                    else:
                        pred, sigma = val, 1.0
                else:
                    if var in preds_all:
                        pred = preds_all[var]["pred"][i]
                        q05, q95 = preds_all[var]["q05"][i], preds_all[var]["q95"][i]
                        sigma = max(0.1, (q95 - q05) / 3.29)
                    else:
                        pred, sigma = val, 1.0
                        
                rd[var] = val - pred
                rd[f"{var}_sigma"] = sigma
            if rd:
                net_resids[(sid, epoch)] = rd
                
    logger.info("Fitting neighbour model …")
    from skyguard.data.registry import neighbours
    train_data = {"T": [], "RH": [], "P": []}
    
    # Use a subset of train_rows for speed
    import random
    random.seed(42)
    sample_train = random.sample(train_rows, min(len(train_rows), 50000))
    for r in sample_train:
        sid = r["station_id"]
        epoch = _fast_epoch(r["ts_utc"])
        target_res = net_resids.get((sid, epoch), {})
        
        nb_sids = neighbours(sid, registry)
        if not nb_sids: continue
        
        n_data = {}
        for nid in nb_sids:
            # allow +/- 30 mins
            for t_off in (0, 15*60, -15*60, 30*60, -30*60):
                n_res = net_resids.get((nid, epoch + t_off))
                if n_res:
                    n_data[nid] = n_res
                    break
                    
        if not n_data: continue
        
        for var in ("T", "RH", "P"):
            if var not in target_res: continue
            f_resid = target_res[var]
            
            var_n_resids = []
            var_n_dists = []
            for nid, n_res in n_data.items():
                if var in n_res:
                    var_n_resids.append(n_res[var])
                    var_n_dists.append(get_neighbour_distance(sid, nid, registry))
                    
            if var_n_resids:
                train_data[var].append((f_resid, var_n_resids, var_n_dists, r.get("source", "unknown")))
                
    det.neighbour_model.fit(train_data)
    
    logger.info("Computing fused residual scores for val_cal …")
    cal_scores = {}
    for r in val_cal_rows:
        sid = r["station_id"]
        epoch = _fast_epoch(r["ts_utc"])
        cadence = r.get("cadence_min", 60)
        target_res = net_resids.get((sid, epoch), {})
        if not target_res: continue
        
        nb_sids = neighbours(sid, registry)
        n_data = {}
        if nb_sids:
            for nid in nb_sids:
                for t_off in (0, 15*60, -15*60, 30*60, -30*60):
                    n_res = net_resids.get((nid, epoch + t_off))
                    if n_res:
                        n_data[nid] = n_res
                        break
                        
        for var in ("T", "RH", "P"):
            if var not in target_res: continue
            f_resid = target_res[var]
            sigma = target_res[f"{var}_sigma"]
            
            var_n_resids = []
            var_n_dists = []
            for nid, n_res in n_data.items():
                if var in n_res:
                    var_n_resids.append(n_res[var])
                    var_n_dists.append(get_neighbour_distance(sid, nid, registry))
                    
            if len(var_n_resids) > 1:
                n_resid_est = det.neighbour_model.predict(var_n_resids, var_n_dists, r.get("source", "unknown"), var)
                sigma_n = max(float(np.std(var_n_resids)), 0.1)
                
                if n_resid_est is None:
                    n_resid_est = float(np.median(var_n_resids))
                    
                w_f = 1.0 / (sigma ** 2)
                w_n = 1.0 / (sigma_n ** 2)
                
                fused_resid = (f_resid * w_f + n_resid_est * w_n) / (w_f + w_n)
                fused_sigma = np.sqrt(1.0 / (w_f + w_n))
                score = abs(fused_resid) / fused_sigma
            else:
                score = abs(f_resid) / sigma
                
            cal_scores.setdefault((var, cadence), []).append(score)
            
    det.calibrator.calibrate(cal_scores)
    train_time = time.perf_counter() - t0

    import pickle
    MODELS_DIR.mkdir(exist_ok=True)
    pkl_path = MODELS_DIR / "detector.pkl"
    with open(pkl_path, "wb") as fh:
        pickle.dump(det, fh)

    pkl_size = pkl_path.stat().st_size
    print("\n" + "=" * 60)
    print("  train.py — SUMMARY")
    print("=" * 60)
    print(f"  Training time      : {train_time:.1f} s")
    print(f"  Model size         : {pkl_size / 1024 / 1024:.1f} MB")
    print(f"  Calibration buckets: {len(cal_scores)}")
    for k, v in sorted(cal_scores.items()):
        print(f"    {k[0]:3s} cad={k[1]:3d}: {len(v):,} scores, "
              f"median={np.median(v):.3f}, p95={np.percentile(v, 95):.3f}")
    print("=" * 60 + "\n")

if __name__ == "__main__":
    train()
