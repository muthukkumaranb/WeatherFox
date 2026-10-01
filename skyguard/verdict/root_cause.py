def classify(features: dict) -> tuple[str, float]:
    batt = features.get("batt_v")
    if batt is not None and batt < 11.0:
        return "power", 0.9
        
    gap = features.get("gap_length_h")
    if gap is not None and gap > 5.0:
        return "comms_gap", 0.9
        
    for var in ("T", "RH", "P"):
        if features.get(f"{var}_is_radiation") == 1:
            return "radiation", 0.8
        if features.get(f"{var}_is_frozen") == 1:
            return "frozen", 0.8
        if features.get(f"{var}_is_spike") == 1:
            return "spike", 0.8
        if features.get(f"{var}_is_offset") == 1:
            return "offset", 0.7
        if features.get(f"{var}_is_drift") == 1:
            return "drift", 0.7
            
    # fallback
    for var in ("T", "RH", "P"):
        r_v = features.get(f"residual_{var}")
        if r_v is not None and abs(r_v) > 5.0:
            return "spike", 0.9
            
    return "unknown", 0.5
