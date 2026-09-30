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

    for var, resid in residuals.items():
        if resid is None or resid == 999.0:
            continue
            
        val = r.get(var)
        if val is None: continue
            
        # Spike: large diff from previous, but previous diff was also large in opposite direction?
        # Actually a spike is when current reading is way off.
        # Let's extract differences:
        diffs = []
        vals = []
        for i in range(len(history)-1, max(-1, len(history)-6), -1):
            if history[i].get(var) is not None:
                vals.append(history[i][var])
        if vals:
            feats[f"{var}_diff_1"] = val - vals[0]
            if len(vals) >= 2:
                feats[f"{var}_diff_2"] = vals[0] - vals[1]
                
        # Frozen: all recent vals are exactly equal to current val
        frozen_cnt = 0
        for v in vals:
            if abs(val - v) < 0.01:
                frozen_cnt += 1
            else:
                break
        feats[f"{var}_frozen_cnt"] = frozen_cnt
        
        # Drift: steady trend in residuals
        # Offset: constant shift in residuals
        dt2 = datetime.datetime.strptime(r["ts_utc"], "%Y-%m-%dT%H:%M:%SZ")
        feats[f"{var}_is_day"] = 1 if r.get("solar_rad", 0) > 50 or (18 > dt2.hour > 6) else 0


    assert_no_leak(feats.keys())
    return feats
