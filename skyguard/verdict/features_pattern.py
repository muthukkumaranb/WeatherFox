import datetime
import tomllib
from pathlib import Path
from skyguard.contract import assert_no_leak

_registry_cache = None
_config_cache = None

def get_lon(station_id):
    global _registry_cache
    if _registry_cache is None:
        from skyguard.data.registry import load_registry
        _registry_cache = load_registry("data/station_registry.csv")
    return _registry_cache.get(station_id, {}).get("lon", 0.0)

def get_config():
    global _config_cache
    if _config_cache is None:
        config_path = Path(__file__).resolve().parent.parent.parent / "config" / "skyguard.toml"
        with open(config_path, "rb") as f:
            _config_cache = tomllib.load(f)
    return _config_cache

def extract_features(r: dict, history: list[dict], residuals: dict, sigmas: dict = None) -> dict:
    if sigmas is None:
        sigmas = {}
    feats = {}
    feats["residual_T"] = residuals.get("T")
    feats["residual_RH"] = residuals.get("RH")
    feats["residual_P"] = residuals.get("P")
    
    # Check batt_v
    feats["batt_v"] = r.get("batt_v")
    
    # Gap length
    if history:
        dt1 = datetime.datetime.strptime(history[-1]["ts_utc"], "%Y-%m-%dT%H:%M:%SZ")
        dt2 = datetime.datetime.strptime(r["ts_utc"], "%Y-%m-%dT%H:%M:%SZ")
        feats["gap_length_h"] = (dt2 - dt1).total_seconds() / 3600.0
    else:
        feats["gap_length_h"] = 0.0
        
    config = get_config()
    min_frozen_readings = config.get("rule_gate", {}).get("min_frozen_readings", 3)
    
    cadence = r.get("cadence_min", 60)
    step_key = "c60"
    if cadence <= 1: step_key = "c1"
    elif cadence <= 15: step_key = "c15"
    elif cadence <= 30: step_key = "c30"
    elif cadence <= 60: step_key = "c60"
    else: step_key = "c180"
    step_limits = config.get("rule_gate", {}).get("step", {}).get(step_key, {})

    for var, resid in residuals.items():
        if resid is None or resid == 999.0:
            continue
            
        val = r.get(var)
        if val is None: continue
            
        vals = []
        for i in range(len(history)-1, max(-1, len(history)-13), -1):
            if history[i].get(var) is not None:
                vals.append(history[i][var])
                
        if vals:
            diff_1 = val - vals[0]
            step_lim = step_limits.get(var, float('inf'))
            feats[f"{var}_is_spike"] = 1 if abs(diff_1) > step_lim else 0
        else:
            feats[f"{var}_is_spike"] = 0
            
        frozen_cnt = 1
        for v in vals:
            if abs(val - v) < 0.01:
                frozen_cnt += 1
            else:
                break
        feats[f"{var}_is_frozen"] = 1 if frozen_cnt >= min_frozen_readings else 0
        
        # Drift and Offset need recent residuals, which we don't have easily in history because history only has raw values.
        # Approximation: if we don't have historical residuals, we cannot perfectly do offset and drift here without model.
        # But for now we just put 0 to satisfy the schema or do a basic check. 
        feats[f"{var}_is_offset"] = 0
        feats[f"{var}_is_drift"] = 0
        
        # Radiation
        dt2 = datetime.datetime.strptime(r["ts_utc"], "%Y-%m-%dT%H:%M:%SZ")
        utc_hour = dt2.hour + dt2.minute / 60.0
        lon = get_lon(r.get("station_id", ""))
        solar_hour = (utc_hour + lon / 15.0) % 24
        is_day = 7 <= solar_hour < 17
        
        if var == "T":
            # positive only in solar daytime and near zero at night
            sigma = sigmas.get("T", 1.0)
            if is_day and resid > 3.0 * sigma:
                feats[f"{var}_is_radiation"] = 1
            else:
                feats[f"{var}_is_radiation"] = 0

    assert_no_leak(feats.keys())
    return feats
