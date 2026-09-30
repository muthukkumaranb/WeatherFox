import calendar
import datetime
import math
import multiprocessing as mp
import os
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
from collections import defaultdict
import numpy as np

from skyguard.contract import to_model_input
from skyguard.detect.detector import get_rh, get_rh_sigma
from skyguard.data.registry import load_registry, get_neighbour_distance, neighbours
from skyguard.verdict.api import get_detector
from skyguard.verdict.features_pattern import extract_features
from skyguard.verdict.root_cause import classify
from skyguard.verdict.severity import compute_severity
from skyguard.verdict.explain import shap_reasons, suggest_action
from skyguard.verdict.correct import correct
from skyguard.verdict.health import update_health
from skyguard.verdict.assemble import assemble_verdict
try:
    from skyguard.ingest.rule_gate import check as rule_gate_check
except ImportError:
    def rule_gate_check(*args, **kwargs):
        return {}

def _fast_epoch(ts: str) -> int:
    return calendar.timegm((int(ts[0:4]), int(ts[5:7]), int(ts[8:10]), int(ts[11:13]), int(ts[14:16]), int(ts[17:19])))

def _get_3h_change_fast(row_idx, s_rows, var):
    val = s_rows[row_idx].get(var)
    if val is None:
        return 0.0
    target_ts = _fast_epoch(s_rows[row_idx]["ts_utc"]) - 3 * 3600
    best_diff = float('inf')
    best_val = None
    for i in range(row_idx - 1, -1, -1):
        hts = _fast_epoch(s_rows[i]["ts_utc"])
        diff = abs(hts - target_ts)
        if diff < best_diff and diff <= 3600:
            best_diff = diff
            best_val = s_rows[i].get(var)
        if hts < target_ts - 3600:
            break
    if best_val is not None:
        return val - best_val
    return 0.0

_worker_det = None
_worker_registry = None

_worker_net_resids = {}
_worker_model_version = None

def init_worker_verdict(registry_path, net_resids, model_version):
    global _worker_det, _worker_registry, _worker_net_resids, _worker_model_version
    import logging
    if _worker_det is None:
        _worker_det = get_detector()
    if _worker_registry is None:
        _worker_registry = load_registry(registry_path)
    _worker_net_resids = net_resids
    _worker_model_version = model_version

def process_station_forecast(args):
    global _worker_det, _worker_registry
    sid, s_rows_or_path, registry_path = args
    import pickle
    if isinstance(s_rows_or_path, str):
        with open(s_rows_or_path, "rb") as f:
            s_rows = pickle.load(f)
    else:
        s_rows = s_rows_or_path
    if _worker_det is None:
        _worker_det = get_detector()
    if _worker_registry is None:
        _worker_registry = load_registry(registry_path)
    det = _worker_det
    history = []
    feats_list = []
    for r in s_rows:
        feats = det.forecaster.extract_features(r, history, det.climatology)
        feats_list.append(feats)
        history.append(r)
        
    x_mat = np.array([[f.get(k) for k in det.forecaster.feature_names] for f in feats_list], dtype=float)
    
    preds_all = {}
    if len(x_mat) > 0:
        for var, model in det.forecaster.models.items():
            preds_all[var] = {
                "pred": model.predict(x_mat),
                "q05": det.forecaster.q05_models[var].predict(x_mat),
                "q95": det.forecaster.q95_models[var].predict(x_mat)
            }
        
    resids = {}
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
                    prev_val = val
                    for j in range(i - 1, -1, -1):
                        hr = s_rows[j]
                        if hr.get(var) is not None:
                            prev_val = hr.get(var)
                            break
                    pred, sigma = prev_val, 1.0
                    
            rd[var] = val - pred
            rd[f"{var}_sigma"] = sigma
            rd[f"{var}_pred"] = pred
            rd[f"{var}_3h"] = _get_3h_change_fast(i, s_rows, var)
        if rd:
            resids[epoch] = rd
    return sid, resids

def process_station_verdicts(args):
    sid, s_rows, resids = args
    det = _worker_det
    registry = _worker_registry
    net_resids = _worker_net_resids
    model_version = _worker_model_version
    
    nb_sids = neighbours(sid, registry)
    config_metar_tol = 1.0 # default config metar tolerance
    
    verdicts = []
    
    for i, r in enumerate(s_rows):
        epoch = _fast_epoch(r["ts_utc"])
        cadence = r.get("cadence_min", 60)
        is_metar = "metar" in r.get("source", "")
        
        target_res = resids.get(epoch, {})
        
        n_data = {}
        for nid in nb_sids:
            # find closest in +/- 30 min (1800s)
            for t_off in (0, 900, -900, 1800, -1800):
                n_res = resids.get(nid, {}).get(epoch + t_off)  # resids here is local_nr
                if n_res:
                    n_data[nid] = n_res
                    break
        
        # Rule gate looks back at most history_hours (24 h); 100 readings >= 50 h at 30-min cadence.
        # Passing the full history made this O(n^2) (every timestamp re-parsed for every reading).
        history_incl_current = s_rows[max(0, i - 99):i + 1]
        rg_results = rule_gate_check(history_incl_current, cadence_min=cadence)
        is_known = sid in det.climatology.stats
        
        var_results = {}
        if not is_known:
            for var in ("T", "RH", "P"):
                val = r.get(var)
                if val is None:
                    continue
                rg_res = rg_results.get(var, {})
                if rg_res.get("fail"):
                    label = "anomaly"
                    sev = "high"
                    conf = 1.0
                    rc = rg_res.get("cause") or rg_res.get("root_cause") or "out_of_range"
                elif rg_res.get("suspect"):
                    label = "uncertain"
                    sev = "medium"
                    conf = 0.5
                    rc = rg_res.get("cause") or rg_res.get("root_cause") or "out_of_range"
                else:
                    label = "normal"
                    sev = "none"
                    conf = 0.0
                    rc = None

                reasons = [{"feature": "model", "value": 0.0, "contribution": 0.0, "text": "station not in the model's training registry; rule checks only"}]
                if label != "normal":
                    reasons.insert(0, {"feature": "rule_gate", "value": 0.0, "contribution": 1.0, "text": rg_res.get("reason", "Rule gate violation")})

                c_val, c_sig, c_met = correct(var, val, None, 1.0, 0)
                h_score, h_trend, h_ttm = update_health(sid, var, label, 999.0 if label != "normal" else 0.0)

                var_results[var] = {
                    "label": label,
                    "p_value": 0.0,
                    "root_cause": rc,
                    "confidence": round(conf, 2),
                    "severity": sev,
                    "reasons": reasons,
                    "action": suggest_action(rc, sev),
                    "spatial_support": "no_model",
                    "corrected": {"value": round(c_val, 1) if c_val is not None else None, "sigma": round(c_sig, 2), "method": c_met},
                    "health": {"score": round(h_score, 2), "trend": h_trend, "ttm_days": h_ttm}
                }
        else:
            for var in ("T", "RH", "P"):
                if var not in target_res:
                    continue
                
            f_resid = target_res[var]
            sigma = target_res[f"{var}_sigma"]
            pred_val = target_res[f"{var}_pred"]
            t_3h = target_res[f"{var}_3h"]
            val = r.get(var)
            
            rg_res = rg_results.get(var, {})
            
            if rg_res.get("fail"):
                label = "anomaly"
                f_resid = 999.0
                sigma = 1.0
                score = abs(f_resid) / sigma
                spatial = "neighbours_normal"
            else:
                var_n_resids = []
                var_n_dists = []
                var_n_3h = []
                
                for nid, n_res in n_data.items():
                    if var in n_res:
                        var_n_resids.append(n_res[var])
                        var_n_dists.append(get_neighbour_distance(sid, nid, registry))
                        var_n_3h.append(n_res[f"{var}_3h"])
                        
                if var_n_resids:
                    n_resid_est = det.neighbour_model.predict(var_n_resids, var_n_dists, r.get("source", ""), var)
                    if n_resid_est is None:
                        n_resid_est = float(np.median(var_n_resids))
                    sigma_n = max(float(np.std(var_n_resids)), 0.1) if len(var_n_resids) > 1 else 1.0
                    
                    w_f = 1.0 / (sigma ** 2)
                    w_n = 1.0 / (sigma_n ** 2)
                    
                    fused_resid = (f_resid * w_f + n_resid_est * w_n) / (w_f + w_n)
                    fused_sigma = np.sqrt(1.0 / (w_f + w_n))
                    score = abs(fused_resid) / fused_sigma
                else:
                    score = abs(f_resid) / sigma
                    
                label, p = det.calibrator.get_labels(score, var, cadence)
                
                if rg_res.get("suspect") and label == "normal":
                    label = "uncertain"
                    
                spatial = "neighbours_normal"
                if label != "normal":
                    from skyguard.detect.event_rule import evaluate_event_rule
                    spatial = evaluate_event_rule(val, pred_val, t_3h, var_n_3h, var_n_resids, config_metar_tol, is_metar)
                    if spatial == "neighbours_also_deviating":
                        label = "normal"
            
            # Now build the verdict for this variable
            feats = extract_features(r, s_rows[:i], {var: f_resid})
            rc, conf = classify(feats)
            
            if rg_res.get("fail") or rg_res.get("suspect"):
                rc = rg_res.get("cause") or rg_res.get("root_cause") or "out_of_range"
                conf = 1.0 if rg_res.get("fail") else 0.5
                
            if label == "normal":
                rc = None
                conf = 0.0
                
            sev = compute_severity(rc, f_resid, conf)
            reasons = shap_reasons(feats, label, f_resid, sigma, var)
            
            if rg_res.get("fail") or rg_res.get("suspect"):
                reasons.insert(0, {"feature": "rule_gate", "value": 0.0, "contribution": 1.0, "text": rg_res.get("reason", "Rule gate violation")})
                
            action = suggest_action(rc, sev)
            c_val, c_sigma, c_method = correct(var, pred_val, None, sigma, 0)
            h_score, h_trend, h_ttm = update_health(sid, var, label, f_resid)
            
            var_res = {
                "label": label,
                "p_value": p if not rg_res.get("fail") else 0.0,
                "root_cause": rc,
                "confidence": round(conf, 2),
                "severity": sev,
                "reasons": reasons,
                "action": action,
                "spatial_support": spatial
            }
            if c_val is not None:
                var_res["corrected"] = {"value": round(c_val, 1), "sigma": round(c_sigma, 2), "method": c_method}
            var_res["health"] = {"score": round(h_score, 2), "trend": h_trend, "ttm_days": h_ttm}
            
            var_results[var] = var_res
            
        if not var_results:
            batt = r.get("batt_v")
            rc = "power" if (batt is not None and batt < 11.0) else "comms_gap"
            for var in ("T", "RH", "P"):
                var_results[var] = {
                    "label": "anomaly",
                    "root_cause": rc,
                    "confidence": 1.0,
                    "severity": "high",
                    "severity_score": 100.0,
                    "reasons": [{"feature": var, "value": 0.0, "contribution": 100.0, "text": "Missing data"}],
                    "action": "flag",
                    "spatial_support": "no_neighbours"
                }
                
        v = assemble_verdict(r, var_results, model_version=model_version)
        verdicts.append(v)
        
    return verdicts

def _verdict_worker(arg):
    sid, s_rows_or_path, s_resids, rp, nr, mv = arg
    import pickle
    if isinstance(s_rows_or_path, str):
        with open(s_rows_or_path, "rb") as f:
            s_rows = pickle.load(f)
    else:
        s_rows = s_rows_or_path
    init_worker_verdict(rp, nr, mv)
    return process_station_verdicts((sid, s_rows, s_resids))

def score_all_batch(all_rows, registry_path: str = "data/station_registry.csv", out_path: str | None = None):
    """Score a DataFrame of readings. With out_path, verdicts are streamed to a JSONL file station by
    station (constant memory for millions of rows) and the number written is returned."""
    # 1. Clean & group
    import math
    import tempfile
    import pickle
    import os
    
    temp_dir = tempfile.mkdtemp()
    by_station_files = {}
    
    # all_rows is a pandas DataFrame
    for sid, group in all_rows.groupby("station_id"):
        s_dicts = group.to_dict('records')
        s_clean = []
        for r in s_dicts:
            rc = {}
            for k, v in r.items():
                if isinstance(v, float) and math.isnan(v):
                    rc[k] = None
                else:
                    rc[k] = v
            rc = to_model_input(rc)
            s_clean.append(rc)
        s_clean.sort(key=lambda x: x["ts_utc"])
        
        filepath = os.path.join(temp_dir, f"{sid}.pkl")
        with open(filepath, "wb") as f:
            pickle.dump(s_clean, f)
        by_station_files[sid] = filepath
        
    # Free the large DataFrame now that everything is on disk
    del all_rows
    import gc
    gc.collect()
        
    # Load the model BEFORE reading its version: importing _model_version first froze it at "untrained".
    import skyguard.verdict.api as _api
    _api.get_detector()
    _model_version = _api._model_version
    from joblib import Parallel, delayed
    from skyguard.data.registry import load_registry, neighbours
    registry = load_registry(registry_path)
    
    # 2. Extract features & predict raw resids (Multiprocessing)
    args_forecast = [(sid, path, registry_path) for sid, path in by_station_files.items()]
    
    results_forecast = Parallel(n_jobs=1, backend="threading")(
        delayed(process_station_forecast)(arg) for arg in args_forecast
    )
        
    station_resids = {}
    for sid, resids in results_forecast:
        station_resids[sid] = resids
            
    # 3. Score final verdicts with neighbours (Multiprocessing)
    args_verdict = []
    for sid, path in by_station_files.items():
        nb_sids = neighbours(sid, registry)
        local_nr = {nid: station_resids[nid] for nid in nb_sids if nid in station_resids}
        args_verdict.append((sid, path, station_resids[sid], registry_path, local_nr, _model_version))
    
    if out_path is not None:
        import json as _json
        n_written = 0
        with open(out_path, "w", encoding="utf-8") as fh:
            for k, arg in enumerate(args_verdict):
                for v in _verdict_worker(arg):
                    fh.write(_json.dumps(v) + "\n")
                    n_written += 1
                if (k + 1) % 25 == 0:
                    print(f"  verdicts: {k + 1}/{len(args_verdict)} stations, {n_written:,} readings", flush=True)
        return n_written

    all_verdicts = []

    results_verdicts = Parallel(n_jobs=1, backend="threading")(
        delayed(_verdict_worker)(arg) for arg in args_verdict
    )

    for vs in results_verdicts:
        all_verdicts.extend(vs)

    all_verdicts.sort(key=lambda x: x["ts_utc"])
    return all_verdicts
