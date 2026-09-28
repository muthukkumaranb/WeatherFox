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

def get_detector():
    global _detector
    if _detector is None:
        try:
            _detector = Detector.load()
        except Exception:
            _detector = Detector()
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
    det_results = det.detect(mod_window, target)
    
    var_results = {}
    
    for var, res in det_results.items():
        feats = extract_features(r, history, {var: res["residual"]})
        
        rc, conf = classify(feats)
        if res["label"] == "normal":
            rc = None
            conf = 0.0
            
        sev = compute_severity(rc, res["residual"], conf)
        
        reasons = shap_reasons(feats)
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
        
    return assemble_verdict(r, var_results)

def score_batch(windows: list[dict], targets: list[str]) -> list[dict]:
    return [score(w, t) for w, t in zip(windows, targets)]
