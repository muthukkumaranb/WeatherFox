def shap_reasons(features: dict, label: str, real_resid: float, real_sigma: float, var: str) -> list[dict]:
    reasons = []
    if label == "normal":
        return reasons
        
    diff = abs(real_resid)
    if real_resid > 0:
        dir_text = "above"
    else:
        dir_text = "below"
        
    sigmas = diff / real_sigma if real_sigma > 0 else 0
    text = f"{var} is {diff:.1f} {'% ' if var == 'RH' else '°C ' if var == 'T' else 'hPa '} {dir_text} forecast ({sigmas:.1f} σ)"
    
    reasons.append({
        "feature": var,
        "value": real_resid,
        "contribution": 1.0,
        "text": text
    })
    return reasons

def suggest_action(root_cause: str, severity: str) -> str:
    actions = {
        "spike": "Inspect sensor wiring; value excluded from products",
        "frozen": "Check sensor response; may need replacement",
        "drift": "Schedule calibration; apply correction",
        "offset": "Check calibration offset",
        "noise": "Inspect connection and shield",
        "out_of_range": "Sensor failure likely",
        "radiation": "Verify radiation shield",
        "power": "Check battery and solar panel",
        "comms_gap": "Check telemetry link",
        "duplicate": "Check ingest logic",
        "timeshift": "Sync datalogger clock",
        "unknown": "Manual review required"
    }
    return actions.get(root_cause, "No action required")
