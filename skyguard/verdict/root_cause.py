def classify(features: dict) -> tuple[str, float]:
    # Check batt and gap first
    batt = features.get("batt_v")
    if batt is not None and batt < 11.0:
        return "power", 0.9
        
    gap = features.get("gap_length_h")
    if gap is not None and gap > 5.0:
        return "comms_gap", 0.9
        
    # Variables that could have been extracted
    for var in ["T", "RH", "P"]:
        resid = features.get(f"residual_{var}")
        if resid is None:
            continue
            
        frozen = features.get(f"{var}_frozen_cnt", 0)
        if frozen >= 3:
            return "frozen", 0.9
            
        diff1 = features.get(f"{var}_diff_1")
        diff2 = features.get(f"{var}_diff_2")
        
        if diff1 is not None and diff2 is not None:
            # single jump then back = spike
            # If current reading is back to normal, then diff1 is large opposite to diff2
            # But wait, if we are classifying the *current* reading which is a spike, 
            # it hasn't gone back yet! 
            pass
            
        if abs(resid) > 5.0:
            is_day = features.get(f"{var}_is_day", 0)
            if var == "T" and resid > 3.0 and is_day:
                return "radiation", 0.8
                
            return "spike", 0.8  # Fallback to spike if large jump
            
    return "unknown", 0.5
