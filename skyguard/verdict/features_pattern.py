def extract_features(r: dict, history: list[dict], residuals: dict) -> dict:
    from skyguard.contract import assert_no_leak
    feats = {}
    feats["residual_T"] = residuals.get("T")
    feats["residual_RH"] = residuals.get("RH")
    feats["residual_P"] = residuals.get("P")
    
    # Check batt_v
    feats["batt_v"] = r.get("batt_v")
    
    # Gap length
    if history:
        import datetime
        dt1 = datetime.datetime.strptime(history[-1]["ts_utc"], "%Y-%m-%dT%H:%M:%SZ")
        dt2 = datetime.datetime.strptime(r["ts_utc"], "%Y-%m-%dT%H:%M:%SZ")
        feats["gap_length_h"] = (dt2 - dt1).total_seconds() / 3600.0
    else:
        feats["gap_length_h"] = 0.0
        
    assert_no_leak(feats.keys())
    return feats
