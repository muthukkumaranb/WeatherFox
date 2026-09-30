def classify(features: dict) -> tuple[str, float]:
    # simple rules-based fallback for now
    r_t = features.get("residual_T")
    if r_t is not None and abs(r_t) > 5.0:
        return "spike", 0.9
        
    batt = features.get("batt_v")
    if batt is not None and batt < 11.0:
        return "power", 0.9
        
    gap = features.get("gap_length_h")
    if gap is not None and gap > 5.0:
        return "comms_gap", 0.9
        
    return "unknown", 0.5
