from skyguard.contract import check_window, to_model_input
from skyguard.detect.detector import Detector
from skyguard.verdict.features_pattern import extract_features
from skyguard.verdict.root_cause import classify
from skyguard.verdict.severity import compute_severity
from skyguard.verdict.explain import shap_reasons, suggest_action
from skyguard.verdict.correct import correct
from skyguard.verdict.health import update_health
from skyguard.verdict.assemble import assemble_verdict

# try to import rule_gate, skip if missing
try:
    from skyguard.ingest.rule_gate import check
except ImportError:
    def check(*args, **kwargs):
        return None

_detector = None
_model_version = "untrained"

def get_detector():
    global _detector, _model_version
    if _detector is None:
        try:
            _detector = Detector.load()
            _model_version = "1.0.0"
        except Exception:
            _detector = Detector()
            _model_version = "untrained"
    return _detector

def score(station_window: dict[str, list[dict]], target: str) -> dict:
    check_window(station_window, target)
    
    # to_model_input strips qc fields
    mod_window = {}
    for sid, rows in station_window.items():
        mod_window[sid] = [to_model_input(r) for r in rows]
        
    target_rows = mod_window[target]
    r = target_rows[-1]
    history = target_rows[:-1]
    
    det = get_detector()
    is_known = target in det.climatology.stats
    var_results = {}
    rg_results = check(history + [r], cadence_min=r.get("cadence_min", 60))
    
    if not is_known:
        for var in ("T", "RH", "P"):
            val = r.get(var)
            if val is None: continue
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
                sev = "low"
                conf = 0.0
                rc = None
                
            reasons = [{"feature": "model", "value": 0.0, "contribution": 0.0, "text": "station not in the model's training registry; rule checks only"}]
            if label != "normal":
                reasons.insert(0, {"feature": "rule_gate", "value": 0.0, "contribution": 1.0, "text": rg_res.get("reason", "Rule gate violation")})
                
            c_val, c_sig, c_met = correct(var, val, None, 1.0, 0)
            h_score, h_trend, h_ttm = update_health(target, var, label, 999.0 if label != "normal" else 0.0)
            
            var_results[var] = {
                "label": label,
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
        det_results = det.detect(mod_window, target)
        
        for var, res in det_results.items():
            rg_res = rg_results.get(var, {})
            real_resid = res["residual"]
            real_sigma = res["sigma"]
            if rg_res.get("fail"):
                res["label"] = "anomaly"
                res["residual"] = 999.0
                res["sigma"] = 1.0
            elif rg_res.get("suspect") and res["label"] == "normal":
                res["label"] = "uncertain"
    
                
            feats = extract_features(r, history, {var: res["residual"]})
            
            rc, conf = classify(feats)
            if rg_res.get("fail") or rg_res.get("suspect"):
                rc = rg_res.get("cause") or rg_res.get("root_cause") or "out_of_range"
                conf = 1.0 if rg_res.get("fail") else 0.5
                
            if res["label"] == "normal":
                rc = None
                conf = 0.0
                
            sev = compute_severity(rc, res["residual"], conf)
            reasons = shap_reasons(feats, res["label"], real_resid, real_sigma, var)
            
            if rg_res.get("fail") or rg_res.get("suspect"):
                reasons.insert(0, {"feature": "rule_gate", "value": 0.0, "contribution": 1.0, "text": rg_res.get("reason", "Rule gate violation")})
                
            action = suggest_action(rc, sev)
            val, sigma, method = correct(var, res["pred"], None, res["sigma"], 0)
            h_score, h_trend, h_ttm = update_health(target, var, res["label"], res["residual"])
            
            var_res = {
                "label": res["label"],
                "root_cause": rc,
                "confidence": round(conf, 2),
                "severity": sev,
                "reasons": reasons,
                "action": action,
                "spatial_support": res["spatial_support"]
            }
            
            if val is not None:
                var_res["corrected"] = {
                    "value": round(val, 1),
                    "sigma": round(sigma, 2),
                    "method": method
                }
                
            var_res["health"] = {
                "score": round(h_score, 2),
                "trend": h_trend,
                "ttm_days": h_ttm
            }
                
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
            
    return assemble_verdict(r, var_results, model_version=_model_version)

def score_batch(windows: list[dict], targets: list[str]) -> list[dict]:
    return [score(w, t) for w, t in zip(windows, targets)]
